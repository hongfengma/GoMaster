# -*- coding: utf-8 -*-
"""围棋棋盘基础逻辑 + 坐标转换（SGF <-> GTP）。

内部坐标约定（与 SGF 一致）：
  - x: 列，0=最左
  - y: 行，0=最上
  - color: 1=黑, 2=白, 0=空
GTP 坐标约定（KataGo 返回/接受）：
  - 列字母 a..s（a=最左）
  - 行数字 1..19（1=最下）
  - 例: 内部 (x=3,y=15) -> GTP "D4"
"""


def sgf_to_xy(coord: str, size: int):
    """SGF 两位字母坐标 -> 内部 (x, y)。coord 为空或 None 表示 pass。"""
    if not coord or len(coord) < 2:
        return None
    x = ord(coord[0]) - ord("a")
    y = ord(coord[1]) - ord("a")
    if not (0 <= x < size and 0 <= y < size):
        return None
    return (x, y)


def xy_to_sgf(x: int, y: int) -> str:
    return chr(ord("a") + x) + chr(ord("a") + y)


def xy_to_gtp(x: int, y: int, size: int) -> str:
    """内部 (x,y) -> KataGo GTP 坐标字符串。
    GTP 列字母跳过 'I'（与数字 1 区分）：A-H=0-7, J-T=8-18。"""
    col_idx = x + 1 if x >= 8 else x
    col = chr(ord("A") + col_idx)
    row = size - y
    return f"{col}{row}"


def gtp_to_xy(coord: str, size: int):
    """KataGo GTP 坐标字符串 -> 内部 (x, y)。pass/resign 返回 None。
    GTP 列字母跳过 'I'，需反向换算：J 起实际列索引 -1。"""
    if not coord or coord.lower() in ("pass", "resign", "null"):
        return None
    coord = coord.strip()
    col = coord[0].upper()
    col_idx = ord(col) - ord("A")
    if col_idx >= 8:  # GTP 跳过 'I'，J 起的实际列需 -1
        col_idx -= 1
    x = col_idx
    rowstr = coord[1:]
    y = size - int(rowstr)
    return (x, y)


class Board:
    def __init__(self, size=19):
        self.size = size
        self.grid = [[0] * size for _ in range(size)]  # 0 空,1 黑,2 白

    def set_stone(self, x, y, color):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.grid[y][x] = color

    def get(self, x, y):
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.grid[y][x]
        return -1

    def clone(self):
        b = Board(self.size)
        b.grid = [row[:] for row in self.grid]
        return b

    def to_rows_str(self):
        """生成 KataGo analysis 需要的局面字符串行列表（行 0 = 顶部）。
        'X'=黑, 'O'=白, '.'=空。"""
        rows = []
        for y in range(self.size):
            row = ""
            for x in range(self.size):
                c = self.grid[y][x]
                row += "X" if c == 1 else ("O" if c == 2 else ".")
            rows.append(row)
        return rows


def gtp_col_label(x: int) -> str:
    """内部列索引 -> GTP 列字母（跳过 I）。x=0 -> 'A'，x=8 -> 'J'。"""
    col_idx = x + 1 if x >= 8 else x
    return chr(ord("A") + col_idx)


def build_grid_from_moves(moves, size):
    """moves: list of (color_char 'B'/'W', sgf_coord)。返回 Board。"""
    b = Board(size)
    for color, coord in moves:
        xy = sgf_to_xy(coord, size)
        if xy is None:
            continue
        b.set_stone(xy[0], xy[1], 1 if color == "B" else 2)
    return b


def board_to_ascii(moves, size, actual_sgf=None, best_sgf=None):
    """把「某手落子前」的局面渲染成 ASCII 棋盘字符串，供 LLM 建立空间认知。

    - 列标签 A..T（跳过 I）从左到右；行标签 1..size 从下到上（与 GTP 完全一致）。
    - X=黑子，O=白子，.=空点。
    - ◆ = 本手实际落子点（尚未落下）；★ = AI 推荐点。两者重合时显示 ★。
    这样模型能直接读出「右上角」「三三」「小目」等方位，避免把变化图当事实。
    """
    b = build_grid_from_moves(moves, size)
    actual_xy = sgf_to_xy(actual_sgf, size) if actual_sgf else None
    best_xy = sgf_to_xy(best_sgf, size) if best_sgf else None

    cols = [gtp_col_label(x) for x in range(size)]
    # 顶部列标签（与棋盘宽度对齐：行号占 3 字符 + 空格 + 每列 2 字符）
    header = "    " + " ".join(cols)
    lines = [header]
    for y in range(size):
        row_num = size - y
        cells = []
        for x in range(size):
            if best_xy and (x, y) == best_xy:
                cells.append("★")          # AI 推荐点优先标记
            elif actual_xy and (x, y) == actual_xy:
                cells.append("◆")          # 实际落子点
            else:
                c = b.get(x, y)
                cells.append("X" if c == 1 else ("O" if c == 2 else "."))
        lines.append(f"{row_num:>3} " + " ".join(cells))
    return "\n".join(lines)
