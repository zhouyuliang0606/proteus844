"""随机电路压测：随机网表 → plan → build → 文件级验收 + 几何不变量。

检查项（都不需要 GUI）：
  1. 每条导线段正交
  2. 每条导线端点都落在某个引脚上（或不悬空）
  3. 文件重建出来的网络 == 意图网络

按 donor 分组，因为器件池不同。
"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.build import writer
from proteus844.route import plan as P
from proteus844.verify import file_netlist as F

G = 254000
KIT = os.path.join(HERE, "donors", "kit.pdsprj")
BASE = os.path.join(HERE, "donors", "base.pdsprj")

# 位号前缀要符合惯例：库会校验 Invalid reference
POOLS = {
    BASE: [("7400", ["A", "B", "Y"], ["A", "B", "C", "D"]),
           ("7410", ["A", "B", "C", "Y"], ["A"]),
           ("RES", ["1", "2"], []),
           ("LOGICSTATE", ["Q0"], [])],
    KIT: [("7430", ["A", "B", "C", "D", "E", "F", "G", "H", "Y"], []),
          ("7448", ["A", "B", "C", "D", "QA", "QB", "QC", "QD"], []),
          ("7404", ["A", "Y"], ["A", "B", "C"]),
          ("RES", ["1", "2"], []),
          ("SW-SPST", ["COM", "NO"], [])],
}


def gen(seed, donor):
    rnd = random.Random(seed)
    comps, used = [], []
    pool = POOLS[donor]
    for i in range(rnd.randint(4, 6)):
        dev, pins, units = rnd.choice(pool)
        pref = {"RES": "R", "LOGICSTATE": "LS", "SW-SPST": "SW",
                "BUZZER": "BZ"}.get(dev, "U")
        ref = f"{pref}{i}" + (":" + rnd.choice(units) if units else "")
        comps.append({"ref": ref, "device": dev, "value": dev,
                      "x": 10 + (i % 3) * 26, "y": 10 + (i // 3) * 26, "rotation": 0})
        used.append((ref, pins))
    free = [(ref, p) for ref, pins in used for p in pins]
    rnd.shuffle(free)
    nets = []
    while len(free) >= 2 and len(nets) < 5:
        a, b = free.pop(), free.pop()
        nets.append({"name": f"N{len(nets)+1}", "pins": [list(a), list(b)]})
    return {"components": comps, "nets": nets, "terminals": []}


def invariants(path, netlist, donor):
    tips = P.pin_table(netlist, donor)
    pins = {(int(v[0]), int(v[1])) for v in tips.values()}
    buf = F.reader.load(path)
    recs, i, diag = [], 0, 0
    while True:
        k = buf.find(b"WIRE", i)
        if k < 0:
            break
        i = k + 1
        if buf[k - 1] != 0x7F or buf[k - 2] != 0x02:
            continue
        n = int.from_bytes(buf[k + 4:k + 8], "big")
        if not (2 <= n <= 64):
            continue
        pts, q = [], k + 9
        for _ in range(n):
            pts.append((round(int.from_bytes(buf[q:q + 4], "little", signed=True) / G),
                        round(int.from_bytes(buf[q + 4:q + 8], "little", signed=True) / G)))
            q += 8
        for a, b in zip(pts, pts[1:]):
            if a[0] != b[0] and a[1] != b[1]:
                diag += 1
        recs.append(pts)
    ends = {}
    for r in recs:
        for pt in (r[0], r[-1]):
            ends[pt] = ends.get(pt, 0) + 1
    dangling = sum(1 for pt, c in ends.items() if pt not in pins and c < 2)
    return {"diag": diag, "dangling": dangling, "wires": len(recs)}


def run(per_donor=15):
    total = ok = 0
    fails = []
    tmp = tempfile.gettempdir()
    for donor in (BASE, KIT):
        for seed in range(per_donor):
            total += 1
            nl = gen(seed * 7 + 1, donor)
            out = os.path.join(tmp, f"fz_{os.path.basename(donor)}_{seed}.pdsprj")
            try:
                doc = P.plan(nl, donor)
                probs = [x for x in P.check(doc)
                         if "平行间距" not in x and "共线重叠" not in x]
                if probs:
                    fails.append((os.path.basename(donor), seed, "plan", str(probs)[:70]))
                    continue
                writer.build(nl, doc, donor, out)
            except Exception as exc:                   # noqa: BLE001
                fails.append((os.path.basename(donor), seed, "exception",
                              f"{type(exc).__name__}: {str(exc)[:60]}"))
                continue
            inv = invariants(out, nl, donor)
            d = F.diff({"nets": nl["nets"]}, out)
            if inv["diag"] or inv["dangling"] or not d["ok"]:
                fails.append((os.path.basename(donor), seed, "invariant",
                              f"斜线{inv['diag']} 悬空{inv['dangling']} {d['summary']}"))
                continue
            ok += 1
    print(f"随机电路 {total} 个：通过 {ok}，失败 {len(fails)}")
    modes = {}
    for donor, seed, kind, msg in fails:
        modes.setdefault(kind, []).append((donor, seed, msg))
    for kind, items in modes.items():
        print(f"  ❌ {kind} ×{len(items)}")
        for donor, seed, msg in items[:4]:
            print(f"      {donor} seed {seed}: {msg}")
    return ok, total


if __name__ == "__main__":
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    ok, total = run(per)
    sys.exit(0 if ok == total else 1)
