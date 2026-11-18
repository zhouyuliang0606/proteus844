"""M1 验证：用真实检测出的线段/结点 + 图上读出的引脚尖，跑建网器。

已知答案（图 1.1）：
  A = LS1 + U1:D.A(13) + U3:B.B(5)
  B = LS2 + U1:D.B(12) + U3:A.A(1)
  C = LS3 + U3:A.B(2)  + U3:B.A(4)
  Y1= U1:D.Y + U4:A.1      Y2= U3:A.Y + U4:A.2     Y3= U3:B.Y + U4:A.13
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))
from proteus844.netlist import trace as T

_FIXTURE = os.path.join(HERE, "tests", "fig11_segments.json")
segs = json.load(open(_FIXTURE, encoding="utf-8"))
if isinstance(segs, dict):
    segs = segs.get("segments", segs.get("segs", []))
segs = [{"a": tuple(s["a"]), "b": tuple(s["b"])} for s in segs]

# 只保留 peak>=2.1 的（真结点），2.0 的是门输出小圆圈
JUNCS = [{"x": 97.0, "y": 53.0}, {"x": 113.5, "y": 125.0},
         {"x": 115.5, "y": 205.0}, {"x": 363.5, "y": 135.0}]

PINS = [
    ("LS1", "Q0", (56, 52.5)), ("LS2", "Q0", (54, 125)), ("LS3", "Q0", (56, 205)),
    ("U1:D", "A", (149, 52.5)), ("U1:D", "B", (149, 69.5)), ("U1:D", "Y", (204, 60.5)),
    ("U3:A", "A", (154, 125)), ("U3:A", "B", (154, 141.5)), ("U3:A", "Y", (210, 134)),
    ("U3:B", "A", (159, 205)), ("U3:B", "B", (159, 222)), ("U3:B", "Y", (215, 213.5)),
    ("U4:A", "A", (274, 126)), ("U4:A", "B", (274, 134)), ("U4:A", "C", (274, 142.5)),
    ("U4:A", "Y", (330, 134.5)),
    ("R14", "1", (363.5, 151)), ("R14", "2", (363.5, 175)),
    ("D2", "A", (363.5, 195)), ("D2", "K", (363.5, 238)),
]
pins = [{"ref": r, "pin": p, "tip": t} for r, p, t in PINS]

BOXES = [(149,44,187,78),(154,116,194,150),(159,197,199,231),(274,117,314,151),(356,149,371,177),(350,188,378,226),(34,44,50,61),(34,116,48,134),(36,197,50,214)]
res = T.trace(segs, JUNCS, pins, tol=3.0, exclude_boxes=BOXES)
print(f"线段 {len(segs)} → 切成 {res['pieces']} 段，节点 {res['nodes']} 个")
print(f"\n识别出的网络 {len(res['nets'])} 个：")
for n in res["nets"]:
    print("  ", n["pins"])
if res["unresolved"]:
    print(f"\n未决 {len(res['unresolved'])} 项：")
    for u in res["unresolved"]:
        print("  ", u)

# 与已知答案比对
EXPECT = [
    {("LS1", "Q0"), ("U1:D", "A"), ("U3:B", "B")},
    {("LS2", "Q0"), ("U1:D", "B"), ("U3:A", "A")},
    {("LS3", "Q0"), ("U3:A", "B"), ("U3:B", "A")},
    {("U1:D", "Y"), ("U4:A", "A")},
    {("U3:A", "Y"), ("U4:A", "B")},
    {("U3:B", "Y"), ("U4:A", "C")},
    {("U4:A", "Y"), ("R14", "1")},
    {("R14", "2"), ("D2", "A")},
]
got = [set(map(tuple, n["pins"])) for n in res["nets"]]
print("\n=== 与已知答案比对 ===")
ok = 0
for e in EXPECT:
    hit = e in got
    ok += hit
    print(f"  {'✅' if hit else '❌'} {sorted(e)}")
print(f"\n{ok}/{len(EXPECT)} 一致")
