# -*- coding: utf-8 -*-
"""验证：真实 moves（大写颜色）能否让 KataGo 返回 moveInfos。"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from katago_engine import KataGoEngine

eng = KataGoEngine()
# 真实 moves（大写颜色，引擎应自动转小写）
moves = [["B", "C3"], ["W", "D4"], ["B", "E5"]]
try:
    resp = eng.analyze(moves, 3, size=9, komi=7.5, max_visits=60, timeout=60)
    print("RESP id:", resp.get("id"))
    print("error field?:", resp.get("error"))
    infos = resp.get("moveInfos", [])
    print("num candidates:", len(infos))
    if infos:
        top = infos[0]
        print("top move:", top.get("move"),
              "winrate:", round(top.get("winrate", 0), 4),
              "scoreLead:", top.get("scoreLead"))
    print("root winrate:", resp.get("rootInfo", {}).get("winrate"))
    print("VERIFY OK" if infos else "VERIFY NO CANDIDATES")
except Exception as e:
    traceback.print_exc()
    print("VERIFY FAIL:", repr(e))
finally:
    eng.close()
