import os
"""共线重叠检测器 —— 只报事实，不做裁决。

用法: python check_overlap.py out.pdsprj [--json]

输出：每处共线重叠属于哪两个网络，以及两种情形：
  · 同网冗余  —— 同一网络的线画重了，电气无关
  · 异网重叠  —— 不同网络压在一起，**需要人/模型判断**：
                 可能是短路，也可能是原图就故意并线（总线、合并画法）

不做 exit(1)。判读交给调用方。
"""
import itertools
import json
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import proteus844.vendor.ref844
import wires as W

U32 = lambda b, o: int.from_bytes(b[o:o + 4], "little")


def load(path):
    dsn = zipfile.ZipFile(path).read("ROOT.DSN")
    recs, _ = proteus844.vendor.ref844.parse(path)
    insts = proteus844.vendor.ref844.instances(dsn)
    ws = W.wires(dsn)

    # 引脚 → 导线起点
    pin_wire = {}
    for k, r in enumerate(recs):
        it = insts[k]
        base = it["at"] + 25
        for j in range(it["pins"]):
            off = U32(dsn, base + 4 * j)
            if off:
                pin_wire.setdefault(off, []).append(r["ref"] or f"#{r['device']}")

    # 导线并查集：共享端点即连通
    starts = [w["start"] for w in ws]
    parent = {s: s for s in starts}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    endmap = {}
    for w in ws:
        for p in (w["points"][0], w["points"][-1]):
            endmap.setdefault(tuple(p), []).append(w["start"])
    for ends in endmap.values():
        for a, b in zip(ends, ends[1:]):
            union(a, b)

    # 每组的网络名 = 该组里最小的那个位号
    groups = {}
    for s in starts:
        groups.setdefault(find(s), []).append(s)
    netname = {}
    for root, members in groups.items():
        names = sorted({n for s in members for n in pin_wire.get(s, [])})
        netname[root] = " / ".join(names) if names else f"孤立@{root}"

    # 切线段
    segs = []
    for w in ws:
        pts = w["points"]
        root = find(w["start"])
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if x1 == x2 and y1 == y2:
                continue
            segs.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                         "h": y1 == y2, "v": x1 == x2,
                         "net": netname[root], "root": root})
    return segs, len(ws)


def overlap(a, b):
    if a["h"] and b["h"] and a["y1"] == b["y1"]:
        lo = max(min(a["x1"], a["x2"]), min(b["x1"], b["x2"]))
        hi = min(max(a["x1"], a["x2"]), max(b["x1"], b["x2"]))
        return max(0, hi - lo)
    if a["v"] and b["v"] and a["x1"] == b["x1"]:
        lo = max(min(a["y1"], a["y2"]), min(b["y1"], b["y2"]))
        hi = min(max(a["y1"], a["y2"]), max(b["y1"], b["y2"]))
        return max(0, hi - lo)
    return 0


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        raise SystemExit("用法: python -m proteus844.verify.overlap <工程.pdsprj>")
    as_json = "--json" in sys.argv
    segs, nwire = load(path)
    G = 254000

    findings = []
    for grp, kind in (([s for s in segs if s["h"]], "水平"),
                      ([s for s in segs if s["v"]], "竖直")):
        for a, b in itertools.combinations(grp, 2):
            ov = overlap(a, b)
            if ov <= 0:
                continue
            same = a["net"] == b["net"]
            findings.append({
                "kind": kind,
                "overlap_units": ov,
                "overlap_grid": round(ov / G, 2),
                "same_net": same,
                "verdict": "同网冗余（电气无关）" if same else "异网重叠（需判断）",
                "net_a": a["net"], "net_b": b["net"],
                "seg_a": [round(a["x1"] / G, 2), round(a["y1"] / G, 2),
                          round(a["x2"] / G, 2), round(a["y2"] / G, 2)],
                "seg_b": [round(b["x1"] / G, 2), round(b["y1"] / G, 2),
                          round(b["x2"] / G, 2), round(b["y2"] / G, 2)],
            })

    if as_json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
        return

    print(f"{path}: {nwire} 条导线 → {len(segs)} 段")
    if not findings:
        print("  未发现任何共线重叠。")
        return
    print(f"  发现 {len(findings)} 处共线重叠：\n")
    for i, f in enumerate(findings, 1):
        print(f"  [{i}] {f['kind']} 重叠 {f['overlap_grid']} 格 —— {f['verdict']}")
        print(f"      网A: {f['net_a']}")
        print(f"      网B: {f['net_b']}")
        print(f"      段A: {f['seg_a']}")
        print(f"      段B: {f['seg_b']}")
    same = sum(1 for f in findings if f["same_net"])
    print(f"\n小计：同网 {same} 处 / 异网 {len(findings) - same} 处")
    print("注：本脚本只报事实。异网重叠是否为缺陷，取决于原图是否本来就把这些线画在一起。")


if __name__ == "__main__":
    main()
