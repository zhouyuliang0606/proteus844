"""查共线重叠：同一根线上有两段来自不同网络的导线。

只作**可读性提示**，不是对错判据 —— Proteus 按端点判连接，
共线重叠不会造成短接，但画面上看着像连在一起。

用法：
    python -m proteus844.verify.overlap 工程.pdsprj
"""
import itertools
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from . import file_netlist as F          # noqa: E402


def load(path):
    """返回 (线段列表, 导线根数)；每段带 net 标签和 h/v 方向。"""
    recs, wires, nets, wire_net = F.rebuild(path, with_wire_net=True)
    segs = []
    for start, pts in wires.items():
        label = wire_net.get(start, "?")
        for a, b in zip(pts, pts[1:]):
            h = a[1] == b[1]
            v = a[0] == b[0]
            if not (h or v):
                continue
            segs.append({"net": label, "h": h, "v": v,
                         "x0": min(a[0], b[0]), "x1": max(a[0], b[0]),
                         "y0": min(a[1], b[1]), "y1": max(a[1], b[1])})
    return segs, len(wires)


def overlap(a, b):
    """两段同向线段共线重叠的长度（native 单位）；不共线返回 0。"""
    if a["h"] and b["h"]:
        if a["y0"] != b["y0"]:
            return 0
        lo, hi = max(a["x0"], b["x0"]), min(a["x1"], b["x1"])
        return max(0, hi - lo)
    if a["v"] and b["v"]:
        if a["x0"] != b["x0"]:
            return 0
        lo, hi = max(a["y0"], b["y0"]), min(a["y1"], b["y1"])
        return max(0, hi - lo)
    return 0


def scan(path):
    segs, nwire = load(path)
    out = []
    for grp in ([s for s in segs if s["h"]], [s for s in segs if s["v"]]):
        for a, b in itertools.combinations(grp, 2):
            ov = overlap(a, b)
            if ov <= 0 or a["net"] == b["net"]:
                continue
            out.append({"from": a["net"], "to": b["net"], "units": ov,
                        "grid": round(ov / 254000, 2),
                        "where": (a["x0"], a["y0"]) if a["h"] else (a["x0"], a["y0"])})
    return {"wires": nwire, "cross_net_overlaps": out,
            "summary": f"{nwire} 根导线，跨网共线重叠 {len(out)} 处"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m proteus844.verify.overlap <工程.pdsprj>")
    r = scan(sys.argv[1])
    print(r["summary"])
    for o in r["cross_net_overlaps"]:
        print(f"  {o['from']} × {o['to']}  {o['grid']} 格  @ {o['where']}")
