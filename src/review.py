# -*- coding: utf-8 -*-
"""端到端复盘编排。

流程：解析 SGF -> 逐手 KataGo 分析（对比 实际落子 / 推荐选点 / 胜率差）
      -> 筛选失误手 -> 调 DeepSeek 生成讲解 -> 输出 Markdown 复盘报告。

新增：progress_cb 回调（供 Web 服务做流式进度推送），函数返回结构化 dict，
方便前端消费（不再只依赖 Markdown 文件）。
"""
import os
import sys

from config import DEFAULT_MAX_VISITS, DEFAULT_THRESHOLD, USER_LEVEL
from go_board import (
    sgf_to_xy,
    xy_to_gtp,
    xy_to_sgf,
    gtp_to_xy,
    board_to_ascii,
)
from sgf_parser import parse_sgf
from katago_engine import KataGoEngine
from explainer import explain_move


def _sgfcoord_to_gtp(sgf_coord, size):
    if not sgf_coord or len(sgf_coord) < 2:
        return "pass"
    xy = sgf_to_xy(sgf_coord, size)
    if xy is None:
        return "pass"
    return xy_to_gtp(xy[0], xy[1], size)


def _to_color_wr(wr, color):
    """KataGo 返回的 winrate 统一为「黑方视角」，这里转换为「当前落子方视角」。
    color 为 'B' 直接取；为 'W' 取 1-wr。"""
    try:
        wr = float(wr)
    except (TypeError, ValueError):
        wr = 0.5
    return wr if color == "B" else 1.0 - wr


# ---------------------------------------------------------------------------
# 分析中缓存：相同局面不重复调用 KataGo。
# 键覆盖 moves/turn/size/komi/max_visits/神经网络；server 进程常驻，因此：
#   - 相邻手天然复用（第 i 手「之后」= 第 i+1 手「之前」）
#   - 同一棋谱重复复盘直接全命中
# 19 路长局提速明显。
# ---------------------------------------------------------------------------
_ANALYSIS_CACHE: dict = {}


def _analyze_cached(eng, moves, turn, size, komi, max_visits, nn_key):
    key = (
        tuple((c, m) for c, m in moves),
        int(turn),
        int(size),
        float(komi),
        int(max_visits),
        str(nn_key),
    )
    hit = _ANALYSIS_CACHE.get(key)
    if hit is not None:
        return hit
    resp = eng.analyze(moves, turn, size=size, komi=komi, max_visits=max_visits)
    # 简易上限保护，避免极长对局反复重跑撑爆内存
    if len(_ANALYSIS_CACHE) > 40000:
        _ANALYSIS_CACHE.clear()
    _ANALYSIS_CACHE[key] = resp
    return resp


def run_review(sgf_path, out_path=None, max_visits=DEFAULT_MAX_VISITS,
               threshold=DEFAULT_THRESHOLD, level=USER_LEVEL,
               progress_cb=None, user_cfg=None):
    with open(sgf_path, "r", encoding="utf-8") as f:
        sgf_text = f.read()

    meta = parse_sgf(sgf_text)
    size = meta["size"]
    komi = meta["komi"]
    moves = meta["moves"]  # list of (color, sgf_coord)
    n = len(moves)

    print(f"[复盘] 棋盘 {size} 路, 贴目 {komi}, 共 {n} 手, 阈值 {threshold:.0%}")

    # KataGo 引擎可配置覆盖（用户设置界面指定本地程序/配置）
    llm_cfg = None
    if user_cfg:
        from userconfig import resolve_katago, llm_section
        ke, kc, kw = resolve_katago(user_cfg.get("katago_exe"),
                                    user_cfg.get("katago_cfg"),
                                    user_cfg.get("nn_path"))
        eng = KataGoEngine(exe=ke, weight=kw, cfg=kc)
        llm_cfg = llm_section(user_cfg)
    else:
        eng = KataGoEngine()
    entries = []
    winrates = []  # 全局胜率曲线：每手落子后的黑方视角胜率序列
    # 棋盘状态（仅记录落子，用于给每个 entry 附带「该手之后完整局面」，
    # 供前端报告视图直接绘制棋盘图例，无需前端重建）。
    board_state = [[None] * size for _ in range(size)]
    try:
        for i in range(n):
            color, sgf_coord = moves[i]
            before_moves = [[moves[j][0], _sgfcoord_to_gtp(moves[j][1], size)]
                            for j in range(i)]
            # 1) 分析“该手之前”的局面 -> 最佳选点 & 其胜率（该方视角）
            try:
                resp_before = _analyze_cached(
                    eng, before_moves, i, size, komi, max_visits, eng.weight)
            except Exception as e:
                print(f"  第{i+1}手 before 分析失败: {e}，跳过")
                continue
            infos = resp_before.get("moveInfos", [])
            if not infos:
                print(f"  第{i+1}手: 无候选，跳过")
                continue
            best = infos[0]
            ai_wr = _to_color_wr(best.get("winrate", 0.5), color)
            best_gtp = best.get("move", "pass").upper()
            best_pv = [c.upper() for c in best.get("pv", [])]
            best_xy = gtp_to_xy(best_gtp, size)
            best_sgf = "PASS" if best_xy is None else xy_to_sgf(*best_xy)
            # 实际落子的 GTP 显示坐标（用于讲解与界面展示）
            actual_gtp = _sgfcoord_to_gtp(sgf_coord, size)
            # 变化树转 SGF 序列，供前端画线
            best_pv_sgf = []
            for c in best_pv[:6]:
                pxy = gtp_to_xy(c, size)
                best_pv_sgf.append("PASS" if pxy is None else xy_to_sgf(*pxy))
            # AI 前三候选（含本手最佳），供讲解做对比
            top3 = []
            for info in infos[:3]:
                tmv = info.get("move", "pass")
                top3.append({
                    "move": tmv.upper(),      # GTP 记号（如 Q16），供讲解使用
                    "wr": _to_color_wr(info.get("winrate", 0.5), color) * 100,
                    "pv": info.get("pv", [])[:5],
                })
            phase = ("布局" if (i + 1) <= max(4, n * 0.25)
                     else ("官子" if (i + 1) > n * 0.75 else "中盘"))

            # 2) 分析“实际落子之后”的局面 -> 取根节点胜率（黑视角）-> 换算该方实际胜率
            after_moves = before_moves + [[color, _sgfcoord_to_gtp(sgf_coord, size)]]
            try:
                resp_after = _analyze_cached(
                    eng, after_moves, i + 1, size, komi, max_visits, eng.weight)
                root_wr = resp_after.get("rootInfo", {}).get("winrate")
                opp_wr = root_wr if root_wr is not None else ai_wr
            except Exception as e:
                print(f"  第{i+1}手 after 分析异常: {e}")
                opp_wr = ai_wr
                root_wr = None
            wr_black = float(root_wr) if root_wr is not None else None
            # KataGo winrate 为黑视角，统一转换到当前落子方视角
            actual_wr = _to_color_wr(opp_wr, color) if opp_wr is not None else ai_wr
            delta = ai_wr - actual_wr

            actual_disp = sgf_coord if (sgf_coord and len(sgf_coord) >= 2) else "PASS"
            entry = {
                "no": i + 1,
                "color": color,
                "actual": actual_gtp,         # GTP 记号（如 D6），供界面展示与讲解（唯一显示字段）
                "actual_sgf": actual_disp,    # SGF 坐标（如 dd），供前端棋盘高亮绘制
                "best": best_gtp,             # GTP 记号（如 F6），供界面展示与讲解（唯一显示字段）
                "best_sgf": best_sgf,         # SGF 坐标，供前端变化图绘制
                "best_pv": best_pv,
                "best_pv_sgf": best_pv_sgf,
                "top3": top3,
                "phase": phase,
                "ai_wr": ai_wr,
                "actual_wr": actual_wr,
                "delta": delta,
                "wr_black": wr_black,  # 该手落子后「黑方视角」胜率，供全局胜率曲线
            }
            # 把当前手落子写入棋盘状态，并附带「该手之后完整局面」供报告图例绘制
            _axy = gtp_to_xy(actual_gtp, size)
            if _axy:
                board_state[_axy[1]][_axy[0]] = color
            entry["stones"] = [
                {"x": x, "y": y, "color": board_state[y][x]}
                for y in range(size)
                for x in range(size)
                if board_state[y][x]
            ]
            entries.append(entry)
            winrates.append({
                "move": i + 1,
                "wr": wr_black,
                "is_mistake": delta >= threshold,
            })
            flag = " ⚠失误" if delta >= threshold else ""
            print(f"  第{i+1}手({color}): 实际 {actual_gtp} / 推荐 {best_gtp} | "
                  f"胜率 {ai_wr*100:.1f}%→{actual_wr*100:.1f}% (差{delta*100:+.1f}%){flag}")
            if progress_cb:
                progress_cb({"type": "move", "entry": dict(entry)})
    finally:
        eng.close()

    # 筛选失误手，按手序升序排列（前端列表按棋谱顺序展示，便于用户顺着看）
    mistakes = [e for e in entries if e["delta"] >= threshold]
    mistakes.sort(key=lambda e: e["no"])

    # 若没有任何失误（极少），取下降最大的一手作为示例
    if not mistakes and entries:
        mistakes = [max(entries, key=lambda e: e["delta"])]

    print(f"[复盘] 命中失误手 {len(mistakes)} 个，开始生成讲解...")
    for e in mistakes:
        recent = []
        # 构造前情：最近若干手坐标（GTP 记号，便于模型定位）
        idx = e["no"] - 1
        start = max(0, idx - 6)
        for j in range(start, idx):
            c, coord = moves[j]
            disp = _sgfcoord_to_gtp(coord, size)
            recent.append(f"{c}{disp}")
        # 生成「本手落子前」的真实局面 ASCII 快照（★=推荐点 ◆=实际点），
        # 让讲解器基于真实盘面而非变化图来讲，并具备左右上下的空间认知。
        coord_actual = moves[idx][1] if 0 <= idx < len(moves) else None
        bxy = (gtp_to_xy(e["best"], size)
               if e.get("best") not in ("PASS", "pass", None) else None)
        best_sgf_for_board = "PASS" if bxy is None else xy_to_sgf(*bxy)
        board_ascii = board_to_ascii(
            moves[:idx], size,
            actual_sgf=coord_actual,
            best_sgf=best_sgf_for_board,
        )
        e["explain"] = explain_move(
            move_no=e["no"],
            color_cn="黑" if e["color"] == "B" else "白",
            actual_sgf=e["actual"],
            best_sgf=e["best"],
            ai_wr=e["ai_wr"] * 100,
            actual_wr=e["actual_wr"] * 100,
            delta=e["delta"] * 100,
            best_pv_gtp=e["best_pv"],
            size=size,
            recent_moves_sgf=recent,
            level=level,
            top3=e.get("top3", []),
            phase=e.get("phase", "中盘"),
            board_ascii=board_ascii,
            llm=llm_cfg,
        )
        if progress_cb:
            progress_cb({"type": "explain", "no": e["no"], "explain": e["explain"]})

    report = _build_report(meta, entries, mistakes, threshold, level, max_visits)
    if out_path is None:
        base = os.path.splitext(os.path.basename(sgf_path))[0]
        out_dir = (user_cfg or {}).get("analysis_dir") if user_cfg else None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{base}-复盘报告.md")
        else:
            out_path = os.path.join(os.path.dirname(sgf_path), f"{base}-复盘报告.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[复盘] 报告已写出: {out_path}")

    result = {
        "report_path": out_path,
        "meta": {
            "size": size,
            "komi": komi,
            "black_name": meta["black_name"],
            "white_name": meta["white_name"],
            "total_moves": n,
        },
        "entries": entries,
        "winrates": winrates,
        "mistakes": [e["no"] for e in mistakes],
        "threshold": threshold,
        "level": level,
        "max_visits": max_visits,
    }
    if progress_cb:
        progress_cb({"type": "done", "result": result})
    return result


def _build_report(meta, entries, mistakes, threshold, level, max_visits):
    size = meta["size"]
    lines = []
    lines.append(f"# 围棋 AI 复盘报告（{size} 路）\n")
    lines.append(f"- 黑方：{meta['black_name'] or '（未署名）'}")
    lines.append(f"- 白方：{meta['white_name'] or '（未署名）'}")
    lines.append(f"- 贴目：{meta['komi']}")
    lines.append(f"- 总手数：{len(meta['moves'])}")
    lines.append(f"- 用户水平：{level}　|　分析精度：maxVisits={max_visits}")
    lines.append(f"- 失误判定：本手胜率较 AI 最佳下降 ≥ {threshold:.0%}\n")

    if mistakes:
        biggest = mistakes[0]
        lines.append(f"## 一句话总览\n")
        lines.append(
            f"本局共标记 **{len(mistakes)}** 个值得讲解的分岔点，"
            f"其中第 **{biggest['no']}** 手（{biggest['color']}）偏差最大"
            f"（胜率下降约 {biggest['delta']*100:.1f} 个百分点）。\n"
        )

    lines.append("## 逐手讲解\n")
    for e in mistakes:
        cn = "黑" if e["color"] == "B" else "白"
        lines.append(f"### 第 {e['no']} 手（{cn}方）\n")
        lines.append("| 项目 | 内容 |")
        lines.append("| --- | --- |")
        lines.append(f"| 实际落子 | **{e['actual']}** |")
        lines.append(f"| AI 推荐 | **{e['best']}** |")
        lines.append(f"| 胜率变化 | {e['ai_wr']*100:.1f}% → {e['actual_wr']*100:.1f}%"
                     f"（下降 {e['delta']*100:.1f} 个百分点） |")
        lines.append("")
        lines.append("**教练讲解：**\n")
        lines.append(e.get("explain", "（无）"))
        lines.append("")
        lines.append("---\n")

    # 附录：完整逐手数据
    lines.append("## 附录：逐手数据明细\n")
    lines.append("| 手 | 方 | 实际 | 推荐 | 胜率(最佳) | 胜率(实际) | Δ |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for e in entries:
        cn = "黑" if e["color"] == "B" else "白"
        mark = "⚠" if e["delta"] >= threshold else ""
        lines.append(
            f"| {e['no']} | {cn} | {e['actual']} | {e['best']} | "
            f"{e['ai_wr']*100:.1f}% | {e['actual_wr']*100:.1f}% | "
            f"{e['delta']*100:+.1f}% {mark} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    pass
