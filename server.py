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
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from config import DEFAULT_MAX_VISITS, DEFAULT_THRESHOLD, USER_LEVEL
from sgf_parser import parse_sgf
from review import run_review

WEB_DIR = os.path.join(HERE, "web")
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
                   level=level, progress_cb=cb)
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
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.normpath(WEB_DIR)):
            self._send(403, {"error": "forbidden"})
            return
        if not os.path.isfile(full):
            self._send(404, {"error": "not found"})
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
    print(f"[服务] 前端目录: {WEB_DIR}")
    print(f"[服务] 按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[服务] 已停止")


if __name__ == "__main__":
    main()
