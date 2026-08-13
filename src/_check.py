# -*- coding: utf-8 -*-
"""快速校验：只跑前 6 手 KataGo 分析（不调 DeepSeek），验证胜率视角修复后数值合理。"""
import sys
sys.path.insert(0, ".")
from katago_engine import KataGoEngine
from sgf_parser import parse_sgf
from go_board import gtp_to_xy, xy_to_sgf
from config import DEFAULT_MAX_VISITS
from review import _sgfcoord_to_gtp, _to_color_wr

sgf = "C:/Users/mhf/WorkBuddy/围棋教练AI复盘/sample/9x9-demo.sgf"
meta = parse_sgf(open(sgf, encoding="utf-8").read())
size = meta["size"]; komi = meta["komi"]; moves = meta["moves"]
print(f"棋盘 {size} 路, 贴目 {komi}, 共 {len(moves)} 手")

eng = KataGoEngine()
for i in range(min(6, len(moves))):
    color, sgf_coord = moves[i]
    before = [[moves[j][0], _sgfcoord_to_gtp(moves[j][1], size)] for j in range(i)]
    try:
        rb = eng.analyze(before, i, size=size, komi=komi, max_visits=80)
    except Exception as e:
        print(f"第{i+1}手 before 失败: {e}"); continue
    infos = rb.get("moveInfos", [])
    if not infos:
        print(f"第{i+1}手 无候选"); continue
    best = infos[0]
    ai_wr = _to_color_wr(best.get("winrate", 0.5), color)
    after = before + [[color, _sgfcoord_to_gtp(sgf_coord, size)]]
    try:
        ra = eng.analyze(after, i + 1, size=size, komi=komi, max_visits=80)
        opp = ra.get("rootInfo", {}).get("winrate", ai_wr)
    except Exception as e:
        print(f"第{i+1}手 after 失败: {e}"); opp = ai_wr
    actual_wr = _to_color_wr(opp, color)
    delta = ai_wr - actual_wr
    best_gtp = best.get("move", "pass")
    best_xy = gtp_to_xy(best_gtp, size)
    best_sgf = "PASS" if best_xy is None else xy_to_sgf(*best_xy)
    print(f"第{i+1}手({color}): 实际 {sgf_coord} / 推荐 {best_sgf} | "
          f"最佳胜率 {ai_wr*100:.1f}% 实际 {actual_wr*100:.1f}% Δ {delta*100:+.1f}%")
eng.close()
print("CHECK DONE")
