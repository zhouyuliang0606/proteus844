"""从 .pdsprj 文件本身重建网络表 —— 不依赖 Proteus 也能验电气。

原理与 Proteus 一致：**连接靠导线端点重合，不靠相交**。
  1. 读所有 WIRE 记录的折点
  2. 折点相同的导线并起来
  3. 引脚记录指向的导线并入同一组
  4. 每组里的引脚就是一个网络

用途：replace `compile_netlist`。有 Proteus 时仍建议用 `verify_netdiff`（引擎级真值），
没 Proteus 时用这个（文件级），能抓出"线没搭上"和"两网被连到一起"。
"""
import collections
import zipfile

from . import reader


class _DSU:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _cdb_pin_names(cdb, ref):
    """CDB 组件记录里的引脚名表（部件级）"""
    if not ref:
        return None
    k = cdb.find(bytes([len(ref)]) + ref.encode())
    if k < 0:
        return None
    q = k + 1 + len(ref)
    n = int.from_bytes(cdb[q:q + 4], "little")
    if not (1 <= n <= 64):
        return None
    names, r = [], q + 4
    for _ in range(n):
        ln = cdb[r]
        names.append(cdb[r + 1:r + 1 + ln].decode("ascii", "replace"))
        r += 1 + ln
        r += 1 + cdb[r]
    return names


def rebuild(project, with_wire_net=False):
    """返回 (components, wires, nets) —— nets 是 {frozenset((ref,pin))}"""
    buf = reader.load(project)
    with zipfile.ZipFile(project) as z:
        cdb = z.read("ROOT.CDB")
    recs, _ = reader.parse(project)

    wires, i = {}, 0
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
        pts, p = [], k + 9
        for _ in range(n):
            pts.append((int.from_bytes(buf[p:p + 4], "little", signed=True),
                        int.from_bytes(buf[p + 4:p + 8], "little", signed=True)))
            p += 8
        wires[k - 25] = pts

    dsu = _DSU()
    at = {}
    for start, pts in wires.items():
        for pt in pts:
            if pt in at:
                dsu.union(("w", start), ("w", at[pt]))
            else:
                at[pt] = start

    pins = []
    for r in recs:
        ref = r["ref"] or f"#{r['device']}"
        names = _cdb_pin_names(cdb, r["ref"]) if r["ref"] else None
        if names is None and r["device"] == "LOGICSTATE":
            names = ["Q0"]
        base = r["instance_offset"] + 25
        for j in range(r["pin_count"]):
            v = int.from_bytes(buf[base + 4 * j:base + 4 * j + 4], "little")
            name = names[j] if names and j < len(names) else f"P{j}"
            node = ("pin", ref, name)
            dsu.find(node)
            if v:
                dsu.union(node, ("w", v))
            pins.append((node, ref, name))

    groups = collections.defaultdict(set)
    for node, ref, name in pins:
        groups[dsu.find(node)].add((ref, name))
    # 保留单引脚网：电源脚没接线时这里必须看得见（否则会掩盖"一个电源符号都没画"）
    nets = [frozenset(v) for v in groups.values() if v]
    if not with_wire_net:
        return recs, wires, nets
    # 每根线属于哪个网 —— check_overlap 需要这个映射
    comp_pins = {}
    for node, ref, name in pins:
        comp_pins.setdefault(dsu.find(node), set()).add((ref, name))
    wire_net = {}
    for start in wires:
        ps = comp_pins.get(dsu.find(("w", start)), set())
        wire_net[start] = ",".join(sorted(f"{r}.{p}" for r, p in ps)) or "?"
    return recs, wires, nets, wire_net


def check_terminals(netlist, project):
    """电源/地端子是否真的挂上了：每个 terminals 条目必须能连到对应引脚。

    之前完全没覆盖 —— 17 个 VCC/GND 丢了也没人发现。
    """
    want = [t for t in (netlist.get("terminals") or [])]
    if not want:
        return {"ok": True, "checked": 0, "missing": []}
    recs, wires, nets = rebuild(project)
    # 重建里终端不参与，所以只能按"该引脚是否出现在某个网络里"间接判断
    in_net = set()
    for n in nets:
        in_net |= set(n)
    missing = [{"pin": t["pin"], "kind": t["kind"], "name": t.get("name")}
               for t in want if tuple(t["pin"]) not in in_net]
    return {"ok": not missing, "checked": len(want), "missing": missing[:12],
            "note": "电源端子必须让引脚进入某个网；缺失说明符号没挂上"}


def diff(netlist, project):
    """意图网表 vs 文件重建 → OK / SHORT / BROKEN / MISSING"""
    recs, wires, rebuilt = rebuild(project)
    report, ok, short, broken = [], 0, 0, 0

    for net in netlist.get("nets", []):
        want = frozenset((r, p) for r, p in net.get("pins", []))
        name = net.get("name", "?")
        if len(want) < 2:
            continue
        if want in rebuilt:
            ok += 1
            report.append({"net": name, "status": "OK", "pins": sorted(want)})
            continue
        superset = [s for s in rebuilt if want < s]
        if superset:
            short += 1
            extra = sorted(superset[0] - want)
            report.append({"net": name, "status": "SHORT", "pins": sorted(want),
                           "extra_pins": extra})
            continue
        partial = [s for s in rebuilt if s & want]
        if partial:
            broken += 1
            got = sorted(set().union(*partial) & want)
            report.append({"net": name, "status": "BROKEN", "pins": sorted(want),
                           "found": got})
            continue
        broken += 1
        report.append({"net": name, "status": "MISSING", "pins": sorted(want)})

    total = ok + short + broken
    tw = check_terminals(netlist, project)
    return {
        "ok": total > 0 and short == 0 and broken == 0 and tw["ok"],
        "terminals": tw,
        "components": len(recs),
        "wires": len(wires),
        "rebuilt_nets": len(rebuilt),
        "summary": {"OK": ok, "SHORT": short, "BROKEN": broken},
        "nets": report,
        "note": "文件级重建（不依赖 Proteus）。有 Proteus 时用 verify_netdiff 更权威。",
    }
