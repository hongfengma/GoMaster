# -*- coding: utf-8 -*-
"""KataGo analysis 引擎封装。

通过 KataGo 的 analysis 引擎协议（JSON over stdin/stdout，KaTrain 同款）启动子进程，
发送局面分析请求，解析返回的 moveInfos（最佳选点 / 胜率 / 变化树）。

CPU 后端：eigen（无独显机器）。坐标统一走 GTP（列字母+行号），由 go_board 做转换。
"""
import json
import os
import subprocess
import threading
import time
import queue

from config import KATAGO_EXE, WEIGHT, ANALYSIS_CFG, KATAGO_BACKEND, KATAGO_THREADS


class KataGoEngine:
    def __init__(self, exe=KATAGO_EXE, weight=WEIGHT, cfg=ANALYSIS_CFG,
                 backend=KATAGO_BACKEND, threads=KATAGO_THREADS):
        self.exe = exe
        self.weight = weight
        self.cfg = cfg
        self.backend = backend
        self.threads = threads
        self._req_id = 0
        self._queue = queue.Queue()
        self.proc = None
        self._reader = None
        self._start()

    def _start(self):
        cwd = os.path.dirname(self.exe)
        cmd = [
            self.exe, "analysis",
            "-config", self.cfg,
            "-model", self.weight,
        ]
        # 关闭 stderr 合并，避免干扰 JSON 读取；stderr 单独丢弃
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # 等待引擎就绪（首行 JSON 或简短握手）
        time.sleep(1.5)
        if self.proc.poll() is not None:
            raise RuntimeError(
                "KataGo 子进程启动失败（已退出）。请检查 katago.exe 与权重路径、"
                "backend 是否匹配（eigenavx2 构建需用 -backend eigen）。"
            )

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 日志行，忽略
                    continue
                self._queue.put(obj)
        except Exception:
            pass

    def analyze(self, moves, analyze_turn, size=19, komi=7.5,
                max_visits=120, timeout=90):
        """分析 analyze_turn 这一手之前的局面。

        moves: GTP 坐标序列 list[ ["B","D4"], ... ]，长度为 analyze_turn
               （即“该手尚未落下”的局面前史）。
        analyze_turn: 要分析的轮次（0=开局黑先）。
        返回: KataGo 响应 dict（含 moveInfos / rootInfo）。
        """
        self._req_id += 1
        rid = str(self._req_id)
        # 颜色统一转小写（KataGo 协议要求 "b"/"w"），避免大小写不匹配被拒
        norm_moves = []
        for mv in moves:
            if isinstance(mv, (list, tuple)) and len(mv) >= 2:
                norm_moves.append([str(mv[0]).lower(), mv[1]])
            else:
                norm_moves.append(mv)
        req = {
            "id": rid,
            "request": "analysis",
            "boardXSize": size,
            "boardYSize": size,
            "rules": "chinese",
            "komi": komi,
            "moves": norm_moves,
            "analyzeTurns": [analyze_turn],
            "maxVisits": max_visits,
            "includePolicy": False,
            "includeOwnership": False,
            "includeMovesOwnership": False,
        }
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()

        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"KataGo 分析超时 (turn={analyze_turn})")
            try:
                obj = self._queue.get(timeout=min(remaining, 2.0))
            except queue.Empty:
                continue
            if isinstance(obj, dict) and obj.get("id") == rid:
                if "error" in obj:
                    raise RuntimeError(
                        f"KataGo 返回错误: {obj.get('error')} (id={rid})")
                # 真正的分析响应包含 moveInfos 或 rootInfo
                if "moveInfos" in obj or "rootInfo" in obj:
                    return obj
                # 仅 warning 之类的非分析响应，继续等待真正的分析 JSON
                continue
            # 其它 id 的响应（理论上不会），放回队列稍后处理
            # 简单起见直接忽略非匹配
        return None

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.write("\n")
                self.proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    # 冒烟测试：开局黑先，应返回胜率约 0.5 附近
    eng = KataGoEngine()
    try:
        resp = eng.analyze([], 0, size=9, komi=7.5, max_visits=60, timeout=120)
        print("RESP id:", resp.get("id"))
        infos = resp.get("moveInfos", [])
        print("top move:", infos[0] if infos else None)
        print("root winrate:", resp.get("rootInfo", {}).get("winrate"))
    finally:
        eng.close()
