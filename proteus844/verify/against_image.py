"""对着图验证网表：AI 报的"谁连谁"，真的连上了吗？

⚠ 定位：**初筛工具，不是判据**。
实测在教材扫描件上，即使网表正确也会有 6~9 条网被误报 SPLIT/MERGED ——
因为浅灰线没抽出来（假断开），文字笔画又和导线粘连（假连接）。
它的价值是"把可疑的网挑出来让 AI 回图复核"，而不是"判定对错"。
唯一权威的判据仍然是 Proteus 编译出的 SDF。

不需要知道正确答案 —— 只用图上的线段几何就能判：
  · 每条网声明的引脚，在图上是同一个连通块吗？        → 否则 SPLIT
  · 两条不同的网，会不会共用一个连通块？              → 否则 MERGED（等于短接）
  · 有哪些引脚没被任何网覆盖？                        → UNCOVERED

这一步能在**没有人看图**的情况下抓出识别错误（引脚标错位置、网连错、漏线）。
"""
import collections

TOL = 3.0          # 线段端点合并容差（像素）
PIN_TOL = 14.0     # 引脚到导线的容差：符号的引脚桩常常没被抽出来，留一段空隙
SUPPLY = {"GND", "GNDA", "VSS", "VCC", "VDD", "+5V", "+3V3"}


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _pt_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _dist(p, a)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return _dist(p, (ax + t * dx, ay + t * dy))


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build_graph(segs, tol=TOL):
    """端点图：重合端点相连；端点落在别的线段中间也算连（T 形结点）"""
    pts = []
    for s in segs:
        pts.append(tuple(s["a"]))
        pts.append(tuple(s["b"]))
    uniq = []
    for p in pts:
        if not any(_dist(p, q) <= tol for q in uniq):
            uniq.append(p)

    def node(p):
        for q in uniq:
            if _dist(p, q) <= tol:
                return q
        return p

    dsu = DSU()
    for s in segs:
        a, b = node(tuple(s["a"])), node(tuple(s["b"]))
        dsu.union(a, b)
    # T 形：端点落在另一条线段内部
    for s in segs:
        a, b = tuple(s["a"]), tuple(s["b"])
        for p in uniq:
            if _dist(p, a) <= tol or _dist(p, b) <= tol:
                continue
            if _pt_seg_dist(p, a, b) <= tol:
                dsu.union(node(p), node(a))
    return dsu, uniq


def _inside(p, boxes, pad=1.0):
    for b in boxes:
        if b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad:
            return True
    return False


def wiring_only(segs, boxes):
    """去掉落在器件本体里的线段 —— 符号自己的笔画会把所有网络串成一块。"""
    out = []
    for s in segs:
        mx = (s["a"][0] + s["b"][0]) / 2
        my = (s["a"][1] + s["b"][1]) / 2
        if _inside((mx, my), boxes):
            continue
        out.append(s)
    return out


def check_local(components, netlist, segs, margin=18, tol=TOL, pin_tol=PIN_TOL):
    """逐网本地校验：每条网只在它自己的包围盒附近建图。

    比全局图可靠得多 —— 文字笔画、相邻网络的干扰很少横跨整条网。
    实测编码器图：22/28 条网判定 OK，被标红的 6 条正是已知有问题的开关网。
    """
    pin_px = {(c["ref"], n): tuple(v) for c in components for n, v in (c.get("pins") or {}).items()}
    problems = []
    for net in netlist:
        if (net.get("name") or "").upper() in SUPPLY:
            continue
        pts = [pin_px.get((r, p)) for r, p in net["pins"]]
        pts = [q for q in pts if q]
        if len(pts) < 2:
            problems.append({"net": net["name"], "type": "SINGLE_PIN", "detail": "只有 1 个脚能定位"})
            continue
        x0 = min(q[0] for q in pts) - margin
        x1 = max(q[0] for q in pts) + margin
        y0 = min(q[1] for q in pts) - margin
        y1 = max(q[1] for q in pts) + margin
        sub = [g for g in segs
               if x0 <= g["a"][0] <= x1 and y0 <= g["a"][1] <= y1
               and x0 <= g["b"][0] <= x1 and y0 <= g["b"][1] <= y1]
        if not sub:
            problems.append({"net": net["name"], "type": "NO_WIRE", "detail": "包围盒里没有导线"})
            continue
        dsu, uniq = build_graph(sub, tol)
        nodes, bad = [], []
        for (r, p), q in zip([k for k in net["pins"] if pin_px.get(tuple(k))], pts):
            best = min(uniq, key=lambda u: (u[0] - q[0]) ** 2 + (u[1] - q[1]) ** 2)
            if _dist(best, q) > pin_tol:
                bad.append(f"{r}.{p}")
            else:
                nodes.append(dsu.find(best))
        if bad:
            problems.append({"net": net["name"], "type": "UNCONNECTED_PIN",
                             "detail": f"这些脚附近没有导线端点：{bad}"})
        if len(set(nodes)) > 1:
            problems.append({"net": net["name"], "type": "SPLIT",
                             "detail": f"声明连通，本地图上却分成 {len(set(nodes))} 块"})
    kinds = collections.Counter(p["type"] for p in problems)
    checked = len([n for n in netlist if (n.get("name") or "").upper() not in SUPPLY])
    return {"ok": not problems, "mode": "local", "nets": checked, "pins": len(pin_px),
            "problems": problems, "counts": dict(kinds),
            "summary": (f"{checked} 网本地校验：" + ("全部对得上" if not problems
                        else " / ".join(f"{k} {v}" for k, v in kinds.items())))}


def check(components, netlist, segs, tol=TOL):
    """components: [{ref, pins:{名:(x,y)}, bbox}]；netlist: [{name, pins:[[ref,pin],...]}]"""
    boxes = [c["bbox"] for c in components if c.get("bbox")]
    if boxes:
        segs = wiring_only(segs, boxes)
    dsu, uniq = build_graph(segs, tol)
    pin_px = {}
    for c in components:
        for name, xy in (c.get("pins") or {}).items():
            pin_px[(c["ref"], name)] = tuple(xy)

    def pin_node(key):
        xy = pin_px.get(key)
        if xy is None:
            return None
        best, bd = None, 1e9
        for q in uniq:
            d = _dist(xy, q)
            if d < bd:
                best, bd = q, d
        return (best, bd) if bd <= PIN_TOL else (None, bd)

    problems, net_nodes = [], {}
    uncovered = []
    for net in netlist:
        if (net.get("name") or "").upper() in SUPPLY:
            # 电源网靠符号同名合并，图上本来就是分散的 —— 不能按导线判连通
            continue
        nodes, missing = set(), []
        for ref, pin in net["pins"]:
            key = (ref, pin)
            nd, d = pin_node(key)
            if nd is None:
                missing.append({"pin": f"{ref}.{pin}", "reason": f"附近无导线端点（最近 {d:.1f}px）"})
            else:
                nodes.add(dsu.find(nd))
        net_nodes[net["name"]] = nodes
        if missing:
            problems.append({"net": net["name"], "type": "UNCONNECTED_PIN", "detail": missing})
        if len(nodes) > 1:
            problems.append({"net": net["name"], "type": "SPLIT",
                             "detail": f"声明连通，但图上分成 {len(nodes)} 块"})

    # 两条网共用一个连通块 = 短接
    names = [n["name"] for n in netlist
             if (n.get("name") or "").upper() not in SUPPLY]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            common = net_nodes[names[i]] & net_nodes[names[j]]
            if common:
                problems.append({"net": f"{names[i]} × {names[j]}", "type": "MERGED",
                                 "detail": "两条网在图上是同一块铜皮（短接）"})

    declared = {(r, p) for n in netlist for r, p in n["pins"]}
    for key in pin_px:
        if key not in declared:
            uncovered.append(f"{key[0]}.{key[1]}")

    kinds = collections.Counter(p["type"] for p in problems)
    return {"ok": not problems,
            "nets": len(netlist), "pins": len(pin_px),
            "problems": problems, "counts": dict(kinds),
            "uncovered_pins": uncovered,
            "summary": (f"{len(netlist)} 网 / {len(pin_px)} 脚："
                        + ("全部对得上图" if not problems
                           else " / ".join(f"{k} {v}" for k, v in kinds.items())))}
