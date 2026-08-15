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
    zone_of_xy,
    zone_of_gtp,
    nearby_stones,
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

    返回 (bad, good, shape_stones)：
      - bad/good：命名由确定性代码给出，LLM 不再自己认形。
      - shape_stones：本手及形成上述棋形的具体坐标集合（GTP），
        供 LLM 引用坐标时作为「可引用清单」。
    """
    bad, good = [], []
    shape_stones = set()
    color = grid[y][x]
    if color == 0:
        return bad, good, shape_stones

    stones, libs = group_and_liberties(grid, x, y, size)
    shape_stones |= stones

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
                shape_stones |= {(xs + a, ys + b) for a in (0, 1) for b in (0, 1)}
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
                shape_stones |= {(x, y), (x + ax, y + ay), (x + bx, y + by)}
                break

    # 好形：对角相连（双）
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == color:
            good.append("双(好形)")
            shape_stones |= {(x, y), (nx, ny)}
            break

    # 好形：拆二（同行/列隔一无子）
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == color:
            mx, my = x + dx // 2, y + dy // 2
            if grid[my][mx] == 0:
                good.append("拆二(好形)")
                shape_stones |= {(x, y), (nx, ny)}
                break

    return bad, good, shape_stones


# ---------------------------------------------------------------------------
# ③ 定式识别（角部定式基底 + 挂角关系 + 偏差检测）
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


def _relation_name(dx, dy):
    """由挂角方相对角部首子的偏移，命名挂角关系。"""
    adx, ady = abs(dx), abs(dy)
    if adx == 0 and ady == 0:
        return ""
    if adx <= 1 and ady <= 1:
        if adx == 1 and ady == 1:
            return "小尖挂"
        return "一间低挂"
    if (adx == 1 and ady == 2) or (adx == 2 and ady == 1):
        return "一间高挂"
    if adx == 2 and ady == 2:
        return "大飞挂"
    if (adx == 2 and ady == 0) or (adx == 0 and ady == 2):
        return "二间低挂"
    if (adx == 0 and ady == 3) or (adx == 3 and ady == 0):
        return "二间高挂"
    if (adx == 1 and ady == 3) or (adx == 3 and ady == 1):
        return "三间高挂"
    return "远夹/拆逼"


# 定式库：key=(角部基底, 挂角关系)，value=常见应手相对首子的偏移集合 (dx,dy)。
# 坐标约定：dx/dy 均指向棋盘内侧（远离角点方向），允许 0；对称型请同时列出两种朝向。
_JOSEKI_LIBRARY = {
    # 星位体系
    ("星位(4-4)", "一间低挂"): {
        (1, 1), (2, 0), (0, 2), (2, 1), (1, 2),
        (3, 0), (0, 3), (3, 1), (1, 3), (2, 2),
    },
    ("星位(4-4)", "一间高挂"): {
        (1, 1), (2, 0), (0, 2), (2, 2), (3, 1),
        (1, 3), (3, 2), (2, 3), (1, -1), (-1, 1),
    },
    ("星位(4-4)", "大飞挂"): {
        (1, 1), (2, 0), (0, 2), (3, 1), (1, 3),
        (3, 2), (2, 3), (3, 3), (2, 2), (1, -1), (-1, 1),
    },
    ("星位(4-4)", "小尖挂"): {
        (2, 0), (0, 2), (2, 1), (1, 2), (2, 2),
        (3, 0), (0, 3), (1, 1),
    },
    ("星位(4-4)", "二间低挂"): {
        (1, 1), (3, 0), (0, 3), (2, 1), (1, 2),
        (3, 1), (1, 3), (2, 2), (2, 0), (0, 2),
    },
    # 小目体系
    ("小目(3-4)", "一间低挂"): {
        (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1),
        (-1, 1), (1, -1), (-1, -1), (2, 0), (0, 2),
        (2, 1), (1, 2), (-2, 0), (0, -2),
    },
    ("小目(3-4)", "一间高挂"): {
        (1, 1), (2, 0), (0, 2), (2, 2), (1, -1),
        (-1, 1), (2, 1), (1, 2), (-1, -1), (0, -1), (-1, 0),
    },
    ("小目(3-4)", "小尖挂"): {
        (2, 0), (0, 2), (2, 1), (1, 2), (-1, 0),
        (0, -1), (1, 1), (-1, 1), (1, -1),
    },
    ("小目(3-4)", "大飞挂"): {
        (1, 1), (2, 0), (0, 2), (2, 2), (3, 1),
        (1, 3), (1, -1), (-1, 1), (-1, -1),
    },
    # 三三体系（对方常高位压迫或低位点三三）
    ("三三(3-3)", "一间低挂"): {
        (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1),
        (-1, 1), (1, -1), (-1, -1), (2, 0), (0, 2),
    },
    ("三三(3-3)", "一间高挂"): {
        (1, 1), (2, 0), (0, 2), (2, 1), (1, 2),
        (-1, 0), (0, -1), (-1, 1), (1, -1),
    },
    ("三三(3-3)", "小尖挂"): {
        (1, 1), (2, 0), (0, 2), (-1, 0), (0, -1),
        (-1, 1), (1, -1),
    },
    # 目外/高目体系（常见为守角或挂角转换）
    ("目外(3-5)", "一间低挂"): {
        (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1),
        (-1, 1), (1, -1), (-1, -1), (2, 0), (0, 2),
    },
    ("高目(4-5)", "一间低挂"): {
        (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1),
        (-1, 1), (1, -1), (-1, -1), (2, 0), (0, 2),
    },
}


def _joseki_replies(base_type, relation):
    return _JOSEKI_LIBRARY.get((base_type, relation)) or set()


def _detect_joseki(moves, upto_i, size, actual_xy):
    """识别该手所属角部的定式基底、挂角关系，并检测是否偏离常见应手。

    返回 {
        "matched": 名称或 None,
        "relation": 挂角关系,
        "step": 角部着手数,
        "deviation": True/False,
        "expected": [GTP, ...] 常见应手,
        "joseki_stones": [GTP, ...] 角部已落子,
        "note": ...
    }。
    """
    empty = {
        "matched": None,
        "relation": "",
        "step": 0,
        "deviation": False,
        "expected": [],
        "joseki_stones": [],
        "note": "",
    }
    if actual_xy is None:
        return {**empty, "note": "无坐标，未识别定式"}
    ax, ay = actual_xy
    cx = 0 if ax < size / 2 else size - 1
    cy = 0 if ay < size / 2 else size - 1
    R = max(5, int(size * 0.30))  # 角部半径

    region = []
    for j in range(upto_i + 1):
        c, coord = moves[j]
        xy = sgf_to_xy(coord, size)
        if xy is None:
            continue
        if abs(xy[0] - cx) <= R and abs(xy[1] - cy) <= R:
            region.append((j, c, xy))
    if len(region) < 2:
        return {**empty, "note": "角部着手过少，未识别定式"}

    first = region[0]
    frx, fry = abs(first[2][0] - cx), abs(first[2][1] - cy)
    otype = _classify_corner_stone(frx, fry)
    if otype is None:
        return {**empty, "note": "首子非标准角部着法"}

    # 收集角部已落子（前 6 手）
    joseki_stones = []
    for _, c, xy in region[:6]:
        joseki_stones.append(xy_to_gtp(xy[0], xy[1], size))

    # 挂角关系：取第一个异色子相对首子的偏移
    opp = [r for r in region if r[1] != first[1]]
    relation = ""
    base_xy = first[2]
    if opp:
        ox, oy = opp[0][2]
        relation = _relation_name(abs(ox - base_xy[0]), abs(oy - base_xy[1]))

    name = otype + ((" · " + relation) if relation else "")

    # 偏差检测：本手相对首子是否落在常见应手集合里
    deviation = False
    expected = []
    replies = _joseki_replies(otype, relation) if relation else set()
    if replies:
        sign_x = 1 if cx == 0 else -1
        sign_y = 1 if cy == 0 else -1
        expected = []
        for dx, dy in replies:
            ex = base_xy[0] + sign_x * dx
            ey = base_xy[1] + sign_y * dy
            if 0 <= ex < size and 0 <= ey < size:
                expected.append(xy_to_gtp(ex, ey, size))
        expected = sorted(set(expected))
        actual_dx = abs(ax - base_xy[0])
        actual_dy = abs(ay - base_xy[1])
        if (actual_dx, actual_dy) not in replies:
            # 只有当本手确实落在角部激战范围内才判偏离（避免把脱先/远场当成定式偏离）
            if max(abs(ax - cx), abs(ay - cy)) <= R:
                deviation = True

    note = ""
    if deviation:
        note = f"本手偏离{otype}+{relation}的常见应手"
    else:
        note = "（常见应手范围内）" if replies else "（定式库暂无该型应手）"

    return {
        "matched": name,
        "relation": relation,
        "step": len(region),
        "deviation": deviation,
        "expected": expected,
        "joseki_stones": joseki_stones,
        "note": note,
    }


# ---------------------------------------------------------------------------
# ④ 失误分类（方向 / 死活 / 官子 / 棋形 / 定式偏离）
# ---------------------------------------------------------------------------
def _classify_mistake(fact, grid_after, size, actual_xy, best_xy, unsettled):
    """为当前失误手打一个主要分类标签。"""
    jt = fact.get("joseki") or {}
    if jt.get("deviation"):
        return "定式偏离"

    phase = fact.get("phase", "")
    if phase == "官子":
        return "官子"

    bad = fact.get("shape_bad", [])
    if "接不归/自紧气" in bad:
        return "死活/战斗"

    # 若落子附近存在气数≤2 的棋子群，视为战斗/死活相关
    if actual_xy:
        ax, ay = actual_xy
        for nx, ny in nearby_stones(grid_after, ax, ay, size, radius=2):
            stones, libs = group_and_liberties(grid_after, nx, ny, size)
            if len(libs) <= 2:
                return "死活/战斗"

    if phase == "布局" and actual_xy and best_xy:
        az = zone_of_xy(*actual_xy, size)
        bz = zone_of_xy(*best_xy, size)
        if az != bz:
            return "方向/大场偏差"
        # 实际与推荐距离较远（>3 路）也视为方向问题
        if max(abs(actual_xy[0] - best_xy[0]), abs(actual_xy[1] - best_xy[1])) > 3:
            return "方向/大场偏差"

    if bad:
        return "棋形"

    if phase == "中盘" and unsettled > 0:
        return "死活/战斗"

    return "局部方向"


# ---------------------------------------------------------------------------
# ⑤ 上下文（不孤立看一步）：目差/领先方/前情趋势
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
    lines.append(f"- 区域：本手 {fact.get('actual','')} 位于「{fact.get('zone','')}」")
    if fact.get("best") and fact.get("best_zone"):
        lines.append(f"- 推荐点区域：{fact['best']} 位于「{fact['best_zone']}」")
    if fact.get("shape_bad"):
        lines.append(f"- 坏形提示：{', '.join(fact['shape_bad'])}")
    if fact.get("shape_good"):
        lines.append(f"- 好形：{', '.join(fact['shape_good'])}")
    involved = fact.get("shape_stones", [])
    if involved:
        lines.append(f"- 涉及坐标（棋形）：{', '.join(involved[:12])}")
    jt = fact.get("joseki") or {}
    if jt.get("matched"):
        lines.append(f"- 定式：{jt['matched']}（角部第 {jt.get('step')} 手）")
        if jt.get("joseki_stones"):
            lines.append(f"- 角部已落子：{', '.join(jt['joseki_stones'][:8])}")
        if jt.get("deviation"):
            lines.append(
                f"- 定式偏离：本手不在 {jt['matched']} 的常见应手内；"
                f"常见应手参考：{', '.join(jt.get('expected', [])[:8])}"
            )
    ctx = fact.get("strategic_context") or {}
    if ctx.get("score_lead") is not None:
        ld = "黑方" if ctx["lead_color"] == "B" else "白方"
        lines.append(f"- 形势：{ld}领先约 {abs(ctx['score_lead']):.1f} 目")
    if ctx.get("recent_trend"):
        lines.append(f"- 走势：{ctx['recent_trend']}")
    if ctx.get("unsettled_groups"):
        lines.append(f"- 未安定大龙：{ctx['unsettled_groups']} 块（注意战斗）")
    if fact.get("category"):
        lines.append(f"- 失误分类：{fact['category']}")
    if fact.get("pv"):
        lines.append(f"- AI 后续主变：{' → '.join(fact['pv'][:5])}")
    lines.append(
        "【坐标铁律】讲解中引用的任何坐标，必须是本事实单里列出的坐标，"
        "或当前手实际/推荐点。禁止凭空编造坐标；第四线及以下为边/角，"
        "第五线及以上为中腹。"
    )
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
    best_xy = gtp_to_xy(best_gtp, size)

    # scoreLead 优先用传入值，否则从 resp_after 解析
    if score_lead is None and resp_after:
        score_lead = (resp_after.get("rootInfo", {}) or {}).get("scoreLead")

    unsettled = count_unsettled(grid_after, size, 2)
    er = empty_ratio(grid_after, size)
    phase, phase_reason = detect_phase(
        i + 1, size, grid_after, score_lead, unsettled, er)

    shape_stones_gtp = []
    if actual_xy:
        bad, good, shape_stone_xy = _detect_shapes(
            grid_after, actual_xy[0], actual_xy[1], size)
        shape_stones_gtp = [xy_to_gtp(x, y, size) for x, y in shape_stone_xy]
    else:
        bad, good = [], []

    joseki = _detect_joseki(moves, i, size, actual_xy)

    ctx = _strategic_context(
        moves, i, size, grid_after, score_lead, unsettled, er, winrates)

    pv = [str(c).upper() for c in (best_pv or []) if c
          and str(c).lower() not in ("pass", "resign")][:6]

    category = ""
    if actual_xy:
        category = _classify_mistake({
            "joseki": joseki,
            "phase": phase,
            "shape_bad": bad,
        }, grid_after, size, actual_xy, best_xy, unsettled)

    fact = {
        "move_no": i + 1,
        "color": color,
        "phase": phase,
        "phase_reason": phase_reason,
        "actual": actual_gtp,
        "best": best_gtp,
        "zone": zone_of_gtp(actual_gtp, size),
        "best_zone": zone_of_gtp(best_gtp, size),
        "shape_tags": bad + good,
        "shape_bad": bad,
        "shape_good": good,
        "shape_stones": shape_stones_gtp,
        "joseki": joseki,
        "category": category,
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
    grid = [[0] * size for _ in range(size)]
    for (x, y) in ((3, 3), (4, 3), (3, 4), (4, 4)):
        grid[y][x] = 1
    grid[7][7] = 2
    bad, good, shape_stones = _detect_shapes(grid, 3, 3, size)
    assert "方四" in bad, f"方四未识别: {bad}"
    assert len(shape_stones) >= 4, f"方四应返回 4 个坐标: {shape_stones}"
    print("  [ok] 方四检测")

    # 空三角检测：黑 (2,2)(3,2)(2,3)，对角 (3,3) 空
    grid2 = [[0] * size for _ in range(size)]
    for (x, y) in ((2, 2), (3, 2), (2, 3)):
        grid2[y][x] = 1
    bad2, _, ss2 = _detect_shapes(grid2, 2, 2, size)
    assert "空三角" in bad2, f"空三角未识别: {bad2}"
    assert len(ss2) == 3, f"空三角应返回 3 个坐标: {ss2}"
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

    # 区域判定：第四线为边，第五线为中腹（以 19 路为例）
    assert zone_of_xy(0, 3, 19) == "角部"
    assert zone_of_xy(3, 10, 19) == "边上"
    assert zone_of_xy(4, 10, 19) == "中腹"
    print("  [ok] 区域判定")

    print("== selftest passed ==")


if __name__ == "__main__":
    _selftest()
