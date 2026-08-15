# -*- coding: utf-8 -*-
"""确定性事实抽取器（GoMaster 解读精准度升级 · Fact Extractor）。

设计原则（对应产品痛点 1/2/3/4）：
  - 别让语言模型去「看」棋盘、识别棋形/定式/阶段——那是它最弱的能力。
  - 把「看懂棋盘」交给确定性程序（规则 + KataGo 的 scoreLead/ownership），
    输出一份结构化「事实单 JSON」，LLM 只负责把事实讲成人话。
  - 全部本地 CPU 跑，零 API 成本。

对外暴露：
  extract_fact(moves, i, size, komi, color, actual_gtp, best_gtp, best_pv,
               resp_before, resp_after, winrates, score_lead=None) -> dict | None
  fact_to_text(fact) -> str   （把事实单渲染成中文段落，供 prompt 使用）

另含 selftest()：用合成棋盘断言气数/棋形/阶段/定式，不依赖 KataGo/网络。
"""
from go_board import (
    build_grid_from_moves,
    gtp_to_xy,
    xy_to_gtp,
    sgf_to_xy,
    group_and_liberties,
    count_unsettled,
    empty_ratio,
)


# ---------------------------------------------------------------------------
# ① 阶段识别（布局 / 中盘 / 官子）
# ---------------------------------------------------------------------------
def detect_phase(move_no, size, grid, score_lead, unsettled, empty_ratio_val):
    """用「空点比例 + 未安定大龙(气数≤2)」综合判定阶段。

    - 布局：尚未发生战斗（无气数≤2 的棋子群）且盘面尚空，属平和展开。
    - 官子：空点很少且无未安定大龙（大局已定，进入收束）。
    - 中盘：存在未安定大龙（战斗）或大局进入中盘。
    注：阈值取 2（真·气紧/对杀），避免把开局单子的 4 气误判为战斗。
    """
    if empty_ratio_val < 0.30 and unsettled == 0:
        sl = f"（目差约 {score_lead:+.1f}）" if score_lead is not None else ""
        return "官子", f"空点很少且无未安定大龙，进入收官阶段{sl}"
    if unsettled == 0 and empty_ratio_val > 0.55:
        return "布局", "尚未发生战斗，处于布局展开"
    if unsettled > 0:
        return "中盘", f"存在 {unsettled} 个气数≤2 的未安定大龙，处于中盘战斗"
    return "中盘", "大局进入中盘"


# ---------------------------------------------------------------------------
# ② 棋形识别（坏形优先标注 + 少量好形）
# ---------------------------------------------------------------------------
def _detect_shapes(grid, x, y, size):
    """在「该手落子后」局面，围绕实际落子 (x,y) 检测棋形。

    返回 (bad, good) 两个标签列表。命名由确定性代码给出，LLM 不再自己认形。
    """
    bad, good = [], []
    color = grid[y][x]
    if color == 0:
        return bad, good

    stones, libs = group_and_liberties(grid, x, y, size)

    # 接不归 / 自紧气：落子后己方该群仅 1 气（且未在本次提子）
    if len(libs) == 1:
        bad.append("接不归/自紧气")

    # 凝形（子力重复）：群子多而气少
    if len(stones) >= 3 and len(libs) <= len(stones):
        bad.append("凝形(子力重复)")

    # 方四：2x2 同色方块
    for sx, sy in ((0, 0), (-1, 0), (0, -1), (-1, -1)):
        xs, ys = x + sx, y + sy
        if 0 <= xs < size - 1 and 0 <= ys < size - 1:
            cells = [grid[ys][xs], grid[ys][xs + 1],
                     grid[ys + 1][xs], grid[ys + 1][xs + 1]]
            if all(c == color for c in cells):
                bad.append("方四")
                break

    # 空三角：L 形三子 + 对角为空
    for ax, ay, bx, by, cx, cy in (
        (1, 0, 0, 1, 1, 1), (-1, 0, 0, 1, -1, 1),
        (1, 0, 0, -1, 1, -1), (-1, 0, 0, -1, -1, -1),
    ):
        if (0 <= x + ax < size and 0 <= y + ay < size
                and 0 <= x + bx < size and 0 <= y + by < size
                and 0 <= x + cx < size and 0 <= y + cy < size):
            if (grid[y + ay][x + ax] == color
                    and grid[y + by][x + bx] == color
                    and grid[y + cy][x + cx] == 0):
                bad.append("空三角")
                break

    # 好形：对角相连（双）
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == color:
            good.append("双(好形)")
            break

    # 好形：拆二（同行/列隔一无子）
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == color:
            mx, my = x + dx // 2, y + dy // 2
            if grid[my][mx] == 0:
                good.append("拆二(好形)")
                break

    return bad, good


# ---------------------------------------------------------------------------
# ③ 定式识别（角部定式基底 + 挂角关系；v1 内置少量常见型，可扩充）
# ---------------------------------------------------------------------------
def _classify_corner_stone(rx, ry):
    """角点相对坐标 (rx,ry) -> 标准角部着法名（0,0=角点）。"""
    if (rx, ry) == (3, 3):
        return "星位(4-4)"
    if (rx, ry) in ((3, 4), (4, 3)):
        return "小目(3-4)"
    if (rx, ry) == (2, 2):
        return "三三(3-3)"
    if (rx, ry) in ((3, 5), (5, 3)):
        return "目外(3-5)"
    if (rx, ry) in ((4, 5), (5, 4)):
        return "高目(4-5)"
    if (rx, ry) == (4, 4):
        return "超高目(5-5)"
    return None


def _detect_joseki(moves, upto_i, size, actual_xy):
    """识别该手所属角部的定式基底与对方挂角关系。

    返回 {"matched": 名称或 None, "step": 角部着手数, "deviation": None, "note": ...}。
    v1 仅做「角部定式基底 + 挂角关系」命名，偏差检测需后续扩充定式库。
    """
    if actual_xy is None:
        return {"matched": None, "note": "无坐标，未识别定式"}
    ax, ay = actual_xy
    cx = 0 if ax < size / 2 else size - 1
    cy = 0 if ay < size / 2 else size - 1
    R = max(5, int(size * 0.30))  # 角部半径（以线数计）

    region = []
    for j in range(upto_i + 1):
        c, coord = moves[j]
        xy = sgf_to_xy(coord, size)
        if xy is None:
            continue
        if abs(xy[0] - cx) <= R and abs(xy[1] - cy) <= R:
            region.append((j, c, xy))
    if len(region) < 2:
        return {"matched": None, "note": "角部着手过少，未识别定式"}

    first = region[0]
    frx, fry = abs(first[2][0] - cx), abs(first[2][1] - cy)
    otype = _classify_corner_stone(frx, fry)
    if otype is None:
        return {"matched": None, "note": "首子非标准角部着法"}

    opp = [r for r in region if r[1] != first[1]]
    relation = ""
    if opp:
        ox, oy = abs(opp[0][2][0] - cx), abs(opp[0][2][1] - cy)
        dx, dy = ox - frx, oy - fry
        adx, ady = abs(dx), abs(dy)
        if adx <= 1 and ady <= 1:
            relation = "贴身/紧气"
        elif (adx == 1 and ady == 2) or (adx == 2 and ady == 1):
            relation = "一间高挂" if max(adx, ady) == 2 else "一间低挂"
        elif adx == 2 and ady == 2:
            relation = "大飞挂"
        else:
            relation = "远夹/拆逼"
    name = otype + ((" · " + relation) if relation else "")
    return {
        "matched": name,
        "step": len(region),
        "deviation": None,
        "note": "（偏差检测需扩充定式库）",
    }


# ---------------------------------------------------------------------------
# ④ 上下文（不孤立看一步）：目差/领先方/前情趋势
# ---------------------------------------------------------------------------
def _strategic_context(moves, i, size, grid_after, score_lead,
                       unsettled, empty_ratio_val, winrates):
    lead_color = "B" if (score_lead is None or score_lead >= 0) else "W"
    recent = []
    start = max(0, i - 5)
    for j in range(start, i + 1):
        c, coord = moves[j]
        xy = sgf_to_xy(coord, size)
        gtp = xy_to_gtp(xy[0], xy[1], size) if xy else "PASS"
        recent.append(f"{c}{gtp}")
    trend = ""
    if winrates:
        seg = [w for w in winrates[max(0, i - 4):i + 1]
               if isinstance(w.get("wr"), (int, float))]
        if len(seg) >= 2:
            trend = (f"近 {len(seg)} 手黑方胜率 "
                     f"{seg[0]['wr'] * 100:.0f}% → {seg[-1]['wr'] * 100:.0f}%")
    return {
        "lead_color": lead_color,
        "score_lead": score_lead,
        "empty_ratio": round(empty_ratio_val, 3),
        "unsettled_groups": unsettled,
        "recent_moves": recent,
        "recent_trend": trend,
    }


# ---------------------------------------------------------------------------
# 事实单渲染（中文段落，供 prompt 使用）
# ---------------------------------------------------------------------------
def fact_to_text(fact):
    if not fact:
        return ""
    lines = []
    lines.append(f"【事实单·系统确定性计算，必须以其为准】")
    lines.append(f"- 阶段：{fact['phase']}（{fact.get('phase_reason','')}）")
    if fact.get("shape_bad"):
        lines.append(f"- 坏形提示：{', '.join(fact['shape_bad'])}")
    if fact.get("shape_good"):
        lines.append(f"- 好形：{', '.join(fact['shape_good'])}")
    jt = fact.get("joseki") or {}
    if jt.get("matched"):
        lines.append(f"- 定式：{jt['matched']}（角部第 {jt.get('step')} 手）")
    ctx = fact.get("strategic_context") or {}
    if ctx.get("score_lead") is not None:
        ld = "黑方" if ctx["lead_color"] == "B" else "白方"
        lines.append(f"- 形势：{ld}领先约 {abs(ctx['score_lead']):.1f} 目")
    if ctx.get("recent_trend"):
        lines.append(f"- 走势：{ctx['recent_trend']}")
    if ctx.get("unsettled_groups"):
        lines.append(f"- 未安定大龙：{ctx['unsettled_groups']} 块（注意战斗）")
    if fact.get("pv"):
        lines.append(f"- AI 后续主变：{' → '.join(fact['pv'][:5])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def extract_fact(moves, i, size, komi, color, actual_gtp, best_gtp,
                 best_pv, resp_before, resp_after, winrates,
                 score_lead=None):
    """抽取第 i 手的事实单。

    参数：
      moves: list[(color_char, sgf_coord)]，完整手序
      i: 当前手索引（0 起）
      size/komi: 棋盘
      color: 'B'/'W'
      actual_gtp/best_gtp: GTP 记号
      best_pv: AI 推荐后续 GTP 序列
      resp_before/resp_after: KataGo 响应（resp_after 需含 rootInfo.scoreLead）
      winrates: 截至当前的全局胜率序列
      score_lead: KataGo rootInfo.scoreLead（黑视角目差），可外部传入
    """
    grid_after = build_grid_from_moves(moves[:i + 1], size).grid
    actual_xy = gtp_to_xy(actual_gtp, size)

    # scoreLead 优先用传入值，否则从 resp_after 解析
    if score_lead is None and resp_after:
        score_lead = (resp_after.get("rootInfo", {}) or {}).get("scoreLead")

    unsettled = count_unsettled(grid_after, size, 2)
    er = empty_ratio(grid_after, size)
    phase, phase_reason = detect_phase(
        i + 1, size, grid_after, score_lead, unsettled, er)

    if actual_xy:
        bad, good = _detect_shapes(grid_after, actual_xy[0], actual_xy[1], size)
    else:
        bad, good = [], []

    joseki = _detect_joseki(moves, i, size, actual_xy)

    ctx = _strategic_context(
        moves, i, size, grid_after, score_lead, unsettled, er, winrates)

    pv = [str(c).upper() for c in (best_pv or []) if c
          and str(c).lower() not in ("pass", "resign")][:6]

    fact = {
        "move_no": i + 1,
        "color": color,
        "phase": phase,
        "phase_reason": phase_reason,
        "actual": actual_gtp,
        "best": best_gtp,
        "shape_tags": bad + good,
        "shape_bad": bad,
        "shape_good": good,
        "joseki": joseki,
        "strategic_context": ctx,
        "pv": pv,
    }
    fact["fact_text"] = fact_to_text(fact)
    return fact


# ---------------------------------------------------------------------------
# 自测（合成棋盘，不依赖 KataGo/网络）
# ---------------------------------------------------------------------------
def _selftest():
    print("== fact_extractor selftest ==")
    size = 9
    # 构造一个「方四」局面：黑在 (3,3)(4,3)(3,4)(4,4) 形成 2x2 方块
    # 另放一白子，保证棋盘非空
    moves = [
        ("B", "dd"), ("W", "pp"),
        ("B", "de"), ("B", "ed"), ("B", "ee"),  # 与 (3,3)=dd 构成 2x2
    ]
    # 注意：上面坐标仅为占位，直接用 grid 构造更可控
    grid = [[0] * size for _ in range(size)]
    for (x, y) in ((3, 3), (4, 3), (3, 4), (4, 4)):
        grid[y][x] = 1
    grid[7][7] = 2
    # 方四检测（以 (3,3) 为锚）
    bad, good = _detect_shapes(grid, 3, 3, size)
    assert "方四" in bad, f"方四未识别: {bad}"
    print("  [ok] 方四检测")

    # 空三角检测：黑 (2,2)(3,2)(2,3)，对角 (3,3) 空
    grid2 = [[0] * size for _ in range(size)]
    for (x, y) in ((2, 2), (3, 2), (2, 3)):
        grid2[y][x] = 1
    bad2, _ = _detect_shapes(grid2, 2, 2, size)
    assert "空三角" in bad2, f"空三角未识别: {bad2}"
    print("  [ok] 空三角检测")

    # 气数：一块黑（单子）应有 4 气
    grid3 = [[0] * size for _ in range(size)]
    grid3[4][4] = 1
    stones, libs = group_and_liberties(grid3, 4, 4, size)
    assert len(libs) == 4, f"单子气数应为4，实得 {len(libs)}"
    print("  [ok] 单子4气")

    # 阶段：空盘+2子 => 布局
    ph, _ = detect_phase(2, size, grid3, None, 0, empty_ratio(grid3, size))
    assert ph == "布局", f"阶段应为布局，实得 {ph}"
    print("  [ok] 阶段-布局")

    # 阶段：满盘(空点极少)且无未安定 => 官子
    grid4 = [[1 if (x + y) % 2 == 0 else 2 for x in range(size)] for y in range(size)]
    ph2, _ = detect_phase(80, size, grid4, 2.0, 0, empty_ratio(grid4, size))
    assert ph2 == "官子", f"阶段应为官子，实得 {ph2}"
    print("  [ok] 阶段-官子")

    # 定式：角部着法分类（相对坐标直接测 classify）
    assert _classify_corner_stone(3, 3) == "星位(4-4)"
    assert _classify_corner_stone(3, 4) == "小目(3-4)"
    assert _classify_corner_stone(2, 2) == "三三(3-3)"
    print("  [ok] 角部着法分类")

    print("== selftest passed ==")


if __name__ == "__main__":
    _selftest()
