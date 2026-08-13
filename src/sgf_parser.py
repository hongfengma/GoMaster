# -*- coding: utf-8 -*-
"""极简 SGF 解析器：提取棋盘尺寸、贴目、落子序列。

只处理最常见的单局 SGF（GM[1]），忽略分支、变着、注解。
返回:
  size: int
  komi: float
  black_name, white_name: str
  moves: list of (color, sgf_coord)  color: 'B'/'W', sgf_coord: 两位字母或 None(pass)
"""
import re


def parse_sgf(text: str):
    # 去掉换行，便于用正则
    text = text.replace("\n", " ").replace("\r", " ")

    size = 19
    komi = 7.5
    black_name = ""
    white_name = ""
    moves = []

    m = re.search(r"SZ\[(\d+)\]", text)
    if m:
        size = int(m.group(1))
    m = re.search(r"KM\[([-\d.]+)\]", text)
    if m:
        try:
            komi = float(m.group(1))
        except ValueError:
            komi = 7.5
    m = re.search(r"PB\[([^\]]*)\]", text)
    if m:
        black_name = m.group(1).strip()
    m = re.search(r"PW\[([^\]]*)\]", text)
    if m:
        white_name = m.group(1).strip()

    # 抓取所有走子属性 B[..] / W[..]（排除 PB/PW/AB/AW 等，用负向回顾确保 B/W 前不是字母）
    for mm in re.finditer(r"(?<![A-Za-z])([BW])\[([^\]]*)\]", text):
        color = mm.group(1)
        coord = mm.group(2).strip()
        coord = coord if len(coord) >= 2 else None
        moves.append((color, coord))

    return {
        "size": size,
        "komi": komi,
        "black_name": black_name,
        "white_name": white_name,
        "moves": moves,
    }
