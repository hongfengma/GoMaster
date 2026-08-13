# -*- coding: utf-8 -*-
"""CLI 入口：对一份 SGF 跑通「KataGo 分析 + DeepSeek 讲解」端到端复盘。

用法:
  python run_review.py                      # 默认用 sample/9x9-demo.sgf
  python run_review.py 路径/xxx.sgf         # 指定棋谱
  python run_review.py 路径/xxx.sgf --visits 200 --threshold 0.06
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from review import run_review
from config import DEFAULT_MAX_VISITS, DEFAULT_THRESHOLD, USER_LEVEL


def main():
    import argparse
    ap = argparse.ArgumentParser()
    default_sgf = os.path.join(HERE, "sample", "9x9-demo.sgf")
    ap.add_argument("sgf", nargs="?", default=default_sgf)
    ap.add_argument("--visits", type=int, default=DEFAULT_MAX_VISITS)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--level", default=USER_LEVEL)
    args = ap.parse_args()

    if not os.path.exists(args.sgf):
        print("找不到棋谱:", args.sgf)
        sys.exit(1)

    out = run_review(args.sgf, max_visits=args.visits,
                    threshold=args.threshold, level=args.level)
    print("完成 ->", out.get("report_path"))


if __name__ == "__main__":
    main()
