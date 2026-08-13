# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, ".")
from katago_engine import KataGoEngine

e = KataGoEngine()
r = e.analyze([], 0, size=9, komi=7.5, max_visits=60, timeout=120)
print("TYPE:", type(r))
print("KEYS:", list(r.keys()) if isinstance(r, dict) else r)
print("REPR:", repr(r)[:4000])
e.close()
