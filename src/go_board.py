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
