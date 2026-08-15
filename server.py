# -*- coding: utf-8 -*-
"""围棋教练 AI 复盘 - 零依赖本地 HTTP 服务。

职责：
  - 托管前端静态资源（web/）
  - POST /api/analyze   接收 SGF 文本，启动后台复盘线程，返回 task_id
  - GET  /api/analyze/<id>  轮询任务进度（逐手 entries / 讲解 / 状态）
  - GET  /api/health    健康检查

启动：python server.py  [端口，默认 8765]
仅依赖 Python 标准库，无需 pip install。
"""
import os
import sys
import io
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 控制台下输出 ★/◆/■ 等 Unicode 时报错。
# 注意：必须在任何 print 之前执行。
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from config import DEFAULT_MAX_VISITS, DEFAULT_THRESHOLD, USER_LEVEL, WEIGHT
from userconfig import load as load_usercfg, save as save_usercfg
from sgf_parser import parse_sgf
from review import run_review

WEB_DIR = os.path.join(HERE, "web")
# 正式前端构建产物（优先）：开发态在 <repo>/frontend/dist；
# 打包态 server.py 位于 resources/，dist 经 --extra-resource 落到 resources/dist。
_candidate_dist = os.path.join(HERE, "frontend", "dist")
if not os.path.isdir(_candidate_dist):
    _candidate_dist = os.path.join(HERE, "dist")
DIST_DIR = _candidate_dist
UPLOAD_DIR = os.path.join(HERE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

tasks = {}
tasks_lock = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _test_llm(llm: dict):
    """测试大模型连接（不校验内容，仅验证连通性与返回结构）。

    兼容 OpenAI 协议：base_url 可为 https://api.deepseek.com/v1 等，
    自动补全 /chat/completions。

    关键降级：用户未填写 api_key 时，自动 fallback 到 config.py 从 .env
    读取的 DEEPSEEK_API_KEY，保证「留空 = 使用 .env 默认 Key」的语义一致。
    """
    import ssl as _ssl
    import urllib.request as _ureq

    from config import DEEPSEEK_API_KEY

    base_url = (llm.get("base_url") or "https://api.deepseek.com/v1").strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        url = base_url
    else:
        url = base_url + "/chat/completions"
    raw_key = (llm.get("api_key") or "").strip()
    used_fallback = False
    if not raw_key:
        raw_key = DEEPSEEK_API_KEY
        used_fallback = True
    payload = {
        "model": llm.get("model") or "deepseek-chat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "temperature": 0,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = _ureq.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with _ureq.urlopen(req, timeout=30, context=_ssl.create_default_context()) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        hint = ""
        if "401" in str(e) or "Authentication" in str(e):
            hint = "（API Key 无效或未填写；留空时将使用 .env 中的默认 Key）"
        return {"ok": False, "error": f"连接失败: {e} {hint}".strip()}
    if resp.get("choices"):
        return {
            "ok": True,
            "model": resp.get("model", llm.get("model")),
            "fallback": used_fallback,
        }
    return {"ok": False, "error": "响应缺少 choices 字段（检查模型名 / 接口路径 / Key）"}


def run_task(task_id, sgf_path, visits, threshold, level):
    """后台线程：跑完整复盘，通过 progress_cb 把数据写回 tasks[task_id]。"""

    def cb(event):
        with tasks_lock:
            t = tasks.get(task_id)
            if not t:
                return
            if event["type"] == "move":
                t["entries"].append(event["entry"])
                t["current"] = event["entry"]["no"]
            elif event["type"] == "explain":
                for e in t["entries"]:
                    if e["no"] == event["no"]:
                        e["explain"] = event["explain"]
                        break
            elif event["type"] == "done":
                t["status"] = "done"
                res = event["result"]
                t["meta"] = res["meta"]
                t["mistakes"] = res["mistakes"]
                t["report_path"] = res["report_path"]

    with tasks_lock:
        tasks[task_id]["status"] = "running"
    try:
        run_review(sgf_path, max_visits=visits, threshold=threshold,
                   level=level, progress_cb=cb, user_cfg=load_usercfg())
    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "error"
            tasks[task_id]["error"] = str(e)


class Handler(BaseHTTPRequestHandler):
    # 静默日志
    def log_message(self, *args, **kwargs):
        pass

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send(200, {"status": "ok"})
            return
        if path == "/api/version":
            self._send(200, {
                "status": "ok",
                "version": "0.9.5",
                "cwd": os.getcwd(),
            })
            return
        if path == "/api/config":
            cfg = load_usercfg()
            # 附带「当前实际使用的神经网络权重」，便于设置界面展示
            cfg["current_nn"] = WEIGHT
            self._send(200, cfg)
            return
        if path.startswith("/api/analyze/"):
            task_id = path.rsplit("/", 1)[-1]
            with tasks_lock:
                t = tasks.get(task_id)
                if not t:
                    self._send(404, {"error": "task not found"})
                    return
                snap = {
                    "task_id": task_id,
                    "status": t["status"],
                    "current": t.get("current"),
                    "meta": t.get("meta"),
                    "entries": t["entries"],
                    "mistakes": t.get("mistakes", []),
                    "error": t.get("error"),
                    "report_path": t.get("report_path"),
                    "created_at": t.get("created_at"),
                }
            self._send(200, snap)
            return
        # 静态资源
        self._serve_static(path)
        return

    def _serve_static(self, path):
        if path == "/" or path == "":
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        # 防目录穿越
        rel = rel.replace("\\", "/")
        # 优先正式前端构建产物（frontend/dist），回退零依赖 MVP（web/）
        full = None
        for base in (DIST_DIR, WEB_DIR):
            norm_base = os.path.normpath(base)
            cand = os.path.normpath(os.path.join(base, rel))
            if cand.startswith(norm_base) and os.path.isfile(cand):
                full = cand
                break
        if full is None:
            # SPA 回退：dist 下未知路径交给 index.html；否则 404
            dist_index = os.path.normpath(os.path.join(DIST_DIR, "index.html"))
            if os.path.isfile(dist_index):
                full = dist_index
            else:
                self._send(404, {"error": "not found"})
                return
        norm_full = os.path.normpath(full)
        if not (norm_full.startswith(os.path.normpath(DIST_DIR))
                or norm_full.startswith(os.path.normpath(WEB_DIR))):
            self._send(403, {"error": "forbidden"})
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
            self._send(200, data, ctype)
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            raw = self._read_body()
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, {"error": "invalid json"})
                return
            try:
                saved = save_usercfg(body)
                self._send(200, saved)
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if parsed.path == "/api/test-llm":
            raw = self._read_body()
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, {"error": "invalid json"})
                return
            try:
                self._send(200, _test_llm(body))
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)})
            return
        if parsed.path != "/api/analyze":
            self._send(404, {"error": "not found"})
            return
        raw = self._read_body()
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send(400, {"error": "invalid json"})
            return

        sgf = (body.get("sgf") or "").strip()
        if not sgf:
            self._send(400, {"error": "缺少 sgf 内容"})
            return

        # 解析元信息（先拿到棋盘尺寸/总手数，供前端初始渲染）
        try:
            meta = parse_sgf(sgf)
            pre_meta = {
                "size": meta["size"],
                "total_moves": len(meta["moves"]),
                "komi": meta["komi"],
                "black_name": meta.get("black_name"),
                "white_name": meta.get("white_name"),
            }
        except Exception as e:
            self._send(400, {"error": f"SGF 解析失败: {e}"})
            return

        task_id = uuid.uuid4().hex[:12]
        sgf_path = os.path.join(UPLOAD_DIR, f"{task_id}.sgf")
        with open(sgf_path, "w", encoding="utf-8") as f:
            f.write(sgf)

        visits = int(body.get("visits", DEFAULT_MAX_VISITS))
        threshold = float(body.get("threshold", DEFAULT_THRESHOLD))
        level = body.get("level", USER_LEVEL)

        with tasks_lock:
            tasks[task_id] = {
                "status": "pending",
                "current": 0,
                "meta": pre_meta,
                "entries": [],
                "mistakes": [],
                "error": None,
                "report_path": None,
                "created_at": __import__("datetime").datetime.now().isoformat(),
            }
        t = threading.Thread(
            target=run_task, args=(task_id, sgf_path, visits, threshold, level),
            daemon=True,
        )
        t.start()
        self._send(200, {"task_id": task_id, "meta": pre_meta})


def main():
    port = 8765
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[服务] 围棋教练复盘服务已启动: http://127.0.0.1:{port}")
    print(f"[服务] 前端目录: {DIST_DIR} (exists={os.path.isdir(DIST_DIR)})")
    print(f"[服务] 按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[服务] 已停止")


if __name__ == "__main__":
    main()
