# -*- coding: utf-8 -*-
"""确定性事实抽取器（GoMaster 解读精准度升级 · Fact Extractor）。

设计原则（对应产品痛点 1/2/3/4）：
  - 别让语言模型去「看」棋盘、识别棋形/定式/阶段——那是它最弱的能力。
  - 把「看懂棋盘」交给确定性程序（规则 + KataGo 的 scoreLead/ownership），
    输出一份结构化「事实单 JSON」，LLM 只负责把事实讲成人话。
  - 全部本地 CPU 跑，零 API 成本。

v1.1.2 升级：
  - 引入 KataGo ownership 整盘领地概率，用于安定度/阶段/方向判断（不再只靠气数）。
  - 坐标「第 N 线」显式锚定（从最近边向里数、1-based），避免 LLM 数错线。
  - 定式识别按「首子→挂角方→应手方」角色识别，当前手角色不清时不硬套定式名。
  - 推荐点也生成事实单（best_fact），约束 LLM 对推荐点的描述，杜绝跨盘拆二幻觉。
  - 方向/压迫/扩张基于落点 ownership 倾向判定。
  - 事实标签增加 confidence，前端只标高置信度标签，避免误导。

对外暴露：
  extract_fact(moves, i, size, komi, color, actual_gtp, best_gtp, best_pv,
               resp_before, resp_after, winrates, score_lead=None) -> dict | None
  fact_to_text(fact) -> str
另含 selftest()。
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
    line_of_xy,
    line_of_gtp,
    ownership_at,
    group_ownership,
    is_stable_group,
)


# ---------------------------------------------------------------------------
# ① 阶段识别（布局 / 中盘 / 官子）
# ---------------------------------------------------------------------------
def detect_phase(move_no, size, grid, score_lead, unsettled, empty_ratio_val):
    """用「空点比例 + 未安定大龙(结合 ownership)」综合判定阶段。

    - 布局：尚未发生战斗（无未安定大龙）且盘面尚空，属平和展开。
    - 官子：空点很少且无未安定大龙（大局已定，进入收束）。
    - 中盘：存在未安定大龙（战斗）或大局进入中盘。
    """
    if empty_ratio_val < 0.30 and unsettled == 0:
        sl = f"（目差约 {score_lead:+.1f}）" if score_lead is not None else ""
        return "官子", f"空点很少且无未安定大龙，进入收官阶段{sl}"
    if unsettled == 0 and empty_ratio_val > 0.55:
        return "布局", "尚未发生战斗，处于布局展开"
    if unsettled > 0:
        return "中盘", f"存在 {unsettled} 个未安定大龙，处于中盘战斗"
    return "中盘", "大局进入中盘"


def count_unstable(grid, ownership, size):
    """统计「未安定大龙」数量：结合气数与 ownership 判定（避免厚势被误判）。

    ownership 可用时：气数>=3 或 群内 ownership 均值|>0.85| 视为安定。
    """
    visited = set()
    count = 0
    for y in range(size):
        for x in range(size):
            if grid[y][x] != 0 and (x, y) not in visited:
                stones, _ = group_and_liberties(grid, x, y, size)
                visited |= stones
                stable, _, _ = is_stable_group(grid, ownership, x, y, size)
                if not stable:
                    count += 1
    return count


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

    # 好形：拆二（同行/列隔一无子，距离=2，确保是真实拆二而非远距）
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
# ③ 定式识别（角部定式基底 + 挂角关系 + 角色识别 + 偏差检测）
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
    """由挂角方相对角部首子的偏移，命名挂角关系（符合中文围棋术语习惯）。

    以 4-4 星位为例（dx/dy 指向棋盘内侧）：
      (1,1)=小尖挂  (1,2)=小飞挂  (1,3)=一间高挂
      (2,2)=二间高挂  (2,3)=大飞挂
      (1,0)=一间低挂  (2,0)=二间低挂  (3,0)=三间低挂
    """
    adx, ady = abs(dx), abs(dy)
    if adx == 0 and ady == 0:
        return ""
    if adx == 1 and ady == 1:
        return "小尖挂"
    if (adx == 1 and ady == 2) or (adx == 2 and ady == 1):
        return "小飞挂"
    if (adx == 1 and ady == 3) or (adx == 3 and ady == 1):
        return "一间高挂"
    if adx == 2 and ady == 2:
        return "二间高挂"
    if (adx == 2 and ady == 3) or (adx == 3 and ady == 2):
        return "大飞挂"
    if adx == 1 and ady == 0 or adx == 0 and ady == 1:
        return "一间低挂"
    if (adx == 2 and ady == 0) or (adx == 0 and ady == 2):
        return "二间低挂"
    if (adx == 3 and ady == 0) or (adx == 0 and ady == 3):
        return "三间低挂"
    return "远夹/拆逼"


# 定式库：key=(角部基底, 挂角关系)，value=常见应手相对首子的偏移集合 (dx,dy)。
# 坐标约定：dx/dy 均指向棋盘内侧（远离角点方向），允许 0；对称型请同时列出两种朝向。
_JOSEKI_LIBRARY = {
    # 星位体系
    ("星位(4-4)", "小飞挂"): {  # 即 keima (1,2) / (2,1)
        (1, 1), (2, 0), (0, 2), (2, 1), (1, 2),
        (3, 0), (0, 3), (3, 1), (1, 3), (2, 2),
    },
    ("星位(4-4)", "一间高挂"): {  # (1,3) / (3,1)
        (1, 1), (2, 0), (0, 2), (2, 2), (3, 1),
        (1, 3), (3, 2), (2, 3), (1, -1), (-1, 1),
    },
    ("星位(4-4)", "大飞挂"): {  # (2,3) / (3,2)
        (1, 1), (2, 0), (0, 2), (3, 1), (1, 3),
        (3, 2), (2, 3), (3, 3), (2, 2), (1, -1), (-1, 1),
    },
    ("星位(4-4)", "小尖挂"): {
        (2, 0), (0, 2), (2, 1), (1, 2), (2, 2),
        (3, 0), (0, 3), (1, 1),
    },
    ("星位(4-4)", "二间低挂"): {  # (2,0) / (0,2)
        (1, 1), (3, 0), (0, 3), (2, 1), (1, 2),
        (3, 1), (1, 3), (2, 2), (2, 0), (0, 2),
    },
    ("星位(4-4)", "二间高挂"): {  # (2,2)
        (1, 1), (2, 0), (0, 2), (2, 1), (1, 2),
        (3, 0), (0, 3), (3, 1), (1, 3), (2, 2),
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


def _detect_joseki(moves, upto_i, size, actual_xy, ownership=None):
    """识别该手所属角部的定式基底、挂角关系，并检测是否偏离常见应手。

    关键改进（v1.1.2）：按「首子→挂角方→应手方」角色识别：
      - 仅把当前手识别为上述角色之一时才给出定式名；
      - 当前手只是落在角部附近、不在定式序列中时，标记为「定式外/脱先」，
        绝不硬套定式名（解决 R14 被误标为「二间低挂」等问题）。
      - 挂角方取「距首子最近的异色子」，而非按落子顺序第一个。
    返回含 confidence 的 dict。
    """
    empty = {
        "matched": None, "relation": "", "role": "", "step": 0,
        "deviation": False, "expected": [], "joseki_stones": [],
        "confidence": "低", "note": "",
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

    # 首子：区域内最早的标准化角部着法
    first = None
    for r in region:
        frx, fry = abs(r[2][0] - cx), abs(r[2][1] - cy)
        if _classify_corner_stone(frx, fry):
            first = r
            break
    if first is None:
        return {**empty, "note": "首子非标准角部着法"}
    otype = _classify_corner_stone(
        abs(first[2][0] - cx), abs(first[2][1] - cy))
    base_xy = first[2]
    joseki_stones = [xy_to_gtp(xy[0], xy[1], size) for _, _, xy in region[:6]]

    # 挂角方：与首子异色、距首子最近者
    opp = [r for r in region if r[1] != first[1]]
    relation = ""
    if opp:
        opp.sort(key=lambda r: abs(r[2][0] - base_xy[0]) + abs(r[2][1] - base_xy[1]))
        ox, oy = opp[0][2]
        relation = _relation_name(
            abs(ox - base_xy[0]), abs(oy - base_xy[1]))

    name = otype + ((" · " + relation) if relation else "")
    replies = _joseki_replies(otype, relation) if relation else set()

    # 当前手角色判定
    is_first = (ax, ay) == tuple(base_xy)
    is_opp = any((ax, ay) == tuple(r[2]) for r in opp)
    actual_dx = abs(ax - base_xy[0])
    actual_dy = abs(ay - base_xy[1])

    role = ""
    confidence = "低"
    deviation = False
    matched_name = None
    if is_first:
        role = "首子"
        confidence = "高"
        matched_name = otype
    elif is_opp:
        role = "挂角"
        confidence = "高" if relation else "中"
        matched_name = name
    else:
        # 同色应手或异色后续应手：看是否在常见应手集合
        if replies and (actual_dx, actual_dy) in replies:
            role = "应手"
            confidence = "高"
            matched_name = name
        elif max(abs(ax - cx), abs(ay - cy)) <= R:
            role = "定式外/脱先"
            confidence = "中"
            deviation = True
            matched_name = None
        else:
            role = "定式外/脱先"
            confidence = "低"
            matched_name = None

    # 偏差检测（应手但不在集合内）
    expected = []
    if replies:
        sign_x = 1 if cx == 0 else -1
        sign_y = 1 if cy == 0 else -1
        for dx, dy in replies:
            ex = base_xy[0] + sign_x * dx
            ey = base_xy[1] + sign_y * dy
            if 0 <= ex < size and 0 <= ey < size:
                expected.append(xy_to_gtp(ex, ey, size))
        expected = sorted(set(expected))
    if role == "应手" and (actual_dx, actual_dy) not in replies:
        deviation = True

    # note 文案
    if role == "首子":
        note = f"角部着法：{otype}"
    elif role == "挂角":
        note = f"对 {otype} 的{relation}"
    elif role == "应手":
        note = (f"{name} 常见应手" if not deviation
                else f"本手偏离{name}常见应手")
    else:
        note = (f"本手位于 {otype} 角部附近，但不属于该定式序列"
                f"（定式外/脱先），不强行命名")

    return {
        "matched": matched_name,
        "relation": relation,
        "role": role,
        "step": len(region),
        "deviation": deviation,
        "expected": expected,
        "joseki_stones": joseki_stones,
        "confidence": confidence,
        "note": note,
    }


# ---------------------------------------------------------------------------
# ④ 失误分类（方向 / 死活 / 官子 / 棋形 / 定式偏离）
# ---------------------------------------------------------------------------
def _detect_connection(grid_after, x, y, size, color):
    """判断一手棋是否具有「连接/补断/边线」特征。

    返回 dict：
      - on_edge_12: 是否落在一/二线（距边 ≤1）
      - connects_groups: 是否把原本不相连的己方两块连起来（补断/联络）
      - neighbor_groups: 落子前邻接的己方棋群数量
      - note: 简短中文说明
    """
    result = {
        "on_edge_12": False,
        "connects_groups": False,
        "neighbor_groups": 0,
        "note": "",
    }
    if x is None or y is None or color not in (1, 2):
        return result

    # 一/二线判定
    edge_dist = min(x, y, size - 1 - x, size - 1 - y)
    result["on_edge_12"] = edge_dist <= 1

    # 临时移除本手棋子，看在没这一手时正交相邻有几块己方棋群
    tmp = [row[:] for row in grid_after]
    tmp[y][x] = 0
    seen_groups = set()
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < size and 0 <= ny < size and tmp[ny][nx] == color:
            stones, _ = group_and_liberties(tmp, nx, ny, size)
            key = tuple(sorted(stones))
            if key not in seen_groups:
                seen_groups.add(key)
    result["neighbor_groups"] = len(seen_groups)
    # 正交连接了 2 块及以上 → 补断/联络
    if len(seen_groups) >= 2:
        result["connects_groups"] = True
        result["note"] = "补断/联络"
    elif result["on_edge_12"]:
        result["note"] = "一二线边线"
    return result


def _analyze_direction(grid, ownership, actual_xy, best_xy, size, color):
    """判断实际落子与推荐点的方向/势力倾向（基于落点 ownership）。

    返回 dict：actual/best 的领地归属倾向，以及二者是否落在不同区域。
    """
    def _terr(xy):
        if not xy:
            return ("", 0.0)
        own = ownership_at(ownership, xy[0], xy[1], size)
        signed = own if color == "B" else -own
        if signed > 0.4:
            return ("己方强势力(扩张/巩固)", signed)
        elif signed < -0.4:
            return ("对方强势力(打入/破空/侵消)", signed)
        return ("双方均势/中腹消长", signed)

    a_terr, a_own = _terr(actual_xy)
    b_terr, b_own = _terr(best_xy)
    diff = ""
    if actual_xy and best_xy:
        az = zone_of_xy(*actual_xy, size)
        bz = zone_of_xy(*best_xy, size)
        if az != bz:
            diff = f"实际在「{az}」、推荐在「{bz}」，方向存在偏差"
    return {
        "actual_territory": a_terr,
        "actual_own": round(a_own, 3),
        "best_territory": b_terr,
        "best_own": round(b_own, 3),
        "region_diff": diff,
    }


def _extract_point_fact(grid, ownership, xy, size, color):
    """为某个落点（实际或推荐）生成轻量事实单（zone/线数/领地倾向）。

    解决「LLM 对推荐点自由发挥、跨盘硬凑拆二」的幻觉：
    把推荐点的真实空间属性也交给事实单约束。
    """
    if not xy:
        return {}
    x, y = xy
    zone = zone_of_xy(x, y, size)
    dir_, no = line_of_xy(x, y, size)
    own = ownership_at(ownership, x, y, size)
    signed = own if color == "B" else -own
    if signed > 0.4:
        territory = "落入己方强势力（扩张/巩固）"
    elif signed < -0.4:
        territory = "落入对方强势力（打入/破空/侵消）"
    else:
        territory = "处于双方均势/中腹消长"
    # 周围 3 格内的棋子（用于判断是否与某子真实相邻）
    nb = nearby_stones(grid, x, y, size, radius=3)
    return {
        "zone": zone,
        "line_dir": dir_,
        "line_no": no,
        "ownership": round(signed, 3),
        "territory": territory,
        "nearby_stones": len(nb),
    }


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

    # 方向偏差：实际与推荐落在不同势力区域（ownership 或 zone 差异）
    direction = fact.get("direction") or {}
    if direction.get("region_diff"):
        return "方向/大场偏差"
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


def _find_move_info(resp, gtp):
    """从 KataGo 响应 moveInfos 里找某 GTP 坐标对应的候选信息。"""
    if not resp:
        return None
    for info in resp.get("moveInfos", []):
        if str(info.get("move", "")).upper() == str(gtp).upper():
            return info
    return None


# ---------------------------------------------------------------------------
# 事实单渲染（中文段落，供 prompt 使用）
# ---------------------------------------------------------------------------
def fact_to_text(fact):
    if not fact:
        return ""
    lines = []
    lines.append("【事实单·系统确定性计算，必须以其为准】")
    lines.append(f"- 阶段：{fact['phase']}（{fact.get('phase_reason','')}）")

    # 线数锚定（v1.1.2 新增，杜绝 LLM 数错第几线）
    if fact.get("line_dir"):
        lines.append(
            f"- 本手 {fact.get('actual','')} 位于「{fact['line_dir']}第"
            f"{fact['line_no']}线」，区域「{fact.get('zone','')}」")
    else:
        lines.append(f"- 区域：本手 {fact.get('actual','')} 位于「{fact.get('zone','')}」")
    if fact.get("best") and fact.get("best_line_dir"):
        lines.append(
            f"- 推荐点 {fact['best']} 位于「{fact['best_line_dir']}第"
            f"{fact['best_line_no']}线」，区域「{fact.get('best_zone','')}」")

    # 推荐点事实单（v1.1.2 新增，约束 LLM 对推荐点的描述）
    bf = fact.get("best_fact") or {}
    if bf:
        lines.append(
            f"- 推荐点事实：{fact.get('best','')} → {bf.get('zone','')} / "
            f"{bf.get('line_dir','')}第{bf.get('line_no','?')}线 / "
            f"{bf.get('territory','')}（ownership={bf.get('ownership','?')}）")

    if fact.get("shape_bad"):
        lines.append(f"- 坏形提示：{', '.join(fact['shape_bad'])}")
    if fact.get("shape_good"):
        lines.append(f"- 好形：{', '.join(fact['shape_good'])}")
    involved = fact.get("shape_stones", [])
    if involved:
        lines.append(f"- 涉及坐标（棋形）：{', '.join(involved[:12])}")
    jt = fact.get("joseki") or {}
    if jt.get("matched"):
        lines.append(f"- 定式：{jt['matched']}（角部第 {jt.get('step')} 手，"
                     f"角色：{jt.get('role','')}）")
        if jt.get("joseki_stones"):
            lines.append(f"- 角部已落子：{', '.join(jt['joseki_stones'][:8])}")
        if jt.get("deviation"):
            lines.append(
                f"- 定式偏离：本手不在 {jt['matched']} 的常见应手内；"
                f"常见应手参考：{', '.join(jt.get('expected', [])[:8])}")
    # 方向/压迫判断（v1.1.2 新增）
    dr = fact.get("direction") or {}
    if dr.get("actual_territory"):
        lines.append(
            f"- 本手境地：{dr['actual_territory']}（ownership={dr.get('actual_own')}）")
    if dr.get("best_territory"):
        lines.append(
            f"- 推荐点境地：{dr['best_territory']}（ownership={dr.get('best_own')}）")
    if dr.get("region_diff"):
        lines.append(f"- 方向提示：{dr['region_diff']}")
    ctx = fact.get("strategic_context") or {}
    if ctx.get("score_lead") is not None:
        ld = "黑方" if ctx["lead_color"] == "B" else "白方"
        lines.append(f"- 形势：{ld}领先约 {abs(ctx['score_lead']):.1f} 目")
    if ctx.get("recent_trend"):
        lines.append(f"- 走势：{ctx['recent_trend']}")
    if ctx.get("unsettled_groups"):
        lines.append(f"- 未安定大龙：{ctx['unsettled_groups']} 块（注意战斗）")
    conn = fact.get("connection") or {}
    if conn.get("connects_groups"):
        lines.append("- 联络特征：本手连接了己方两块棋，具有补断/联络作用，不可描述为「隔离/分断」")
    if conn.get("on_edge_12"):
        lines.append("- 边线提示：本手落在一/二线，属于靠近边线/底线，必须描述为「边线」「一二线」或「靠近边」，绝不可说「中腹」")
    if fact.get("category"):
        lines.append(f"- 失误分类：{fact['category']}")
    if fact.get("pv"):
        lines.append(f"- AI 后续主变：{' → '.join(fact['pv'][:5])}")
    lines.append(
        "【坐标铁律】讲解中引用的任何坐标，必须是本事实单里列出的坐标，"
        "或当前手实际/推荐点。禁止凭空编造坐标；第四线及以下为边/角，"
        "第五线及以上为中腹；一二线必须描述为边线/底线，不能叫中腹。"
    )
    lines.append(
        "【禁止误判】若事实单写明「补断/联络」，你绝不可把本手讲成「隔离」「分断」「切断」对方；"
        "若写明「边线提示」，必须承认它靠近边线。"
    )
    lines.append(
        "【禁止跨盘关联】描述某点与周边子的关系时，只能引用距该点 3 格以内的棋子；"
        "严禁把相距较远的子（例如同列但隔了多条线，或对角远子）说成「拆二」「配合」「压迫」。"
        "推荐点的「境地/区域」以【推荐点事实】为准，不得自行构造跨盘关系。"
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
      resp_before/resp_after: KataGo 响应（resp_after 需含 ownership 顶层数组）
      winrates: 截至当前的全局胜率序列
      score_lead: KataGo rootInfo.scoreLead（黑视角目差），可外部传入
    """
    grid_after = build_grid_from_moves(moves[:i + 1], size).grid
    actual_xy = gtp_to_xy(actual_gtp, size)
    best_xy = gtp_to_xy(best_gtp, size)

    # ownership（优先 after 顶层；无则 before）
    ownership = None
    if resp_after:
        ownership = resp_after.get("ownership")
    if ownership is None and resp_before:
        ownership = resp_before.get("ownership")

    # scoreLead 优先用传入值，否则从 resp_after 解析
    if score_lead is None and resp_after:
        score_lead = (resp_after.get("rootInfo", {}) or {}).get("scoreLead")

    # KataGo 额外字段（容错）
    root = (resp_after or {}).get("rootInfo", {}) or {}
    score_selfplay = root.get("scoreSelfplay")
    score_stdev = root.get("scoreStdev")
    expected_score = root.get("expectedScore")
    actual_info = _find_move_info(resp_before, actual_gtp)

    # 未安定大龙（结合 ownership 过滤厚势）
    unsettled = count_unstable(grid_after, ownership, size)
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

    joseki = _detect_joseki(moves, i, size, actual_xy, ownership)

    # 连接/补断/边线特征（帮助 LLM 避免把 S14 这样的补断说成「隔离」）
    color_num = 1 if color == "B" else 2
    connection = _detect_connection(
        grid_after, actual_xy[0], actual_xy[1], size, color_num) if actual_xy else {
        "on_edge_12": False, "connects_groups": False,
        "neighbor_groups": 0, "note": ""
    }

    # 线数锚定
    line_dir, line_no = line_of_xy(*actual_xy, size) if actual_xy else ("", -1)
    best_dir, best_no = line_of_xy(*best_xy, size) if best_xy else ("", -1)

    # 方向/压迫判断
    direction = _analyze_direction(
        grid_after, ownership, actual_xy, best_xy, size, color)

    # 推荐点事实单
    best_fact = _extract_point_fact(grid_after, ownership, best_xy, size, color)

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
            "direction": direction,
        }, grid_after, size, actual_xy, best_xy, unsettled)

    # 置信度（供前端过滤标签）
    confidence = "低"
    if bad or (joseki.get("role") in ("首子", "挂角", "应手") and not joseki.get("deviation")):
        confidence = "高"
    elif direction.get("region_diff") or joseki.get("matched"):
        confidence = "中"

    fact = {
        "move_no": i + 1,
        "color": color,
        "phase": phase,
        "phase_reason": phase_reason,
        "actual": actual_gtp,
        "best": best_gtp,
        "zone": zone_of_gtp(actual_gtp, size),
        "best_zone": zone_of_gtp(best_gtp, size),
        # 线数锚定（v1.1.2）
        "line_dir": line_dir,
        "line_no": line_no,
        "best_line_dir": best_dir,
        "best_line_no": best_no,
        "shape_tags": bad + good,
        "shape_bad": bad,
        "shape_good": good,
        "shape_stones": shape_stones_gtp,
        "joseki": joseki,
        "category": category,
        "connection": connection,
        "direction": direction,
        "best_fact": best_fact,
        "strategic_context": ctx,
        "confidence": confidence,
        # KataGo 原始信号（供前端/调试）
        "katago": {
            "score_selfplay": score_selfplay,
            "score_stdev": score_stdev,
            "expected_score": expected_score,
            "actual_prior": (actual_info or {}).get("prior"),
            "actual_score_lead": (actual_info or {}).get("scoreLead"),
        },
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

    # 线数锚定：R14（内部 x=16,y=5,size=19）应为「右边第三线」
    d, n = line_of_xy(16, 5, 19)
    assert (d, n) == ("右边", 3), f"R14 应为右边第三线, 实得 {d}{n}"
    assert line_of_xy(3, 3, 19) == ("左边", 4) or line_of_xy(3, 3, 19) == ("上边", 4)
    print("  [ok] 第 N 线判定（R14=右边第三线）")

    # 定式角色识别：当前手为角部脱先时应标记「定式外」（复现 R14 误标问题）
    # 黑星位 pd(14,3)，白小飞挂 pe(14,4)，黑 R14(16,5) 不在该定式序列
    moves = [("B", "pd"), ("W", "pe"), ("B", "R14")]
    jt = _detect_joseki(moves, 2, 19, gtp_to_xy("R14", 19))
    assert jt["role"] in ("定式外/脱先",), f"应识别为定式外, 实得 {jt['role']}"
    assert jt["matched"] is None, f"脱先手不应硬套定式名, 实得 {jt['matched']}"
    print("  [ok] 定式角色-脱先识别（R14 不再误标为二间低挂）")

    print("== selftest passed ==")


if __name__ == "__main__":
    _selftest()
