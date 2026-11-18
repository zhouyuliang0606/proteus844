"""由几何建网：线段 + 结点 + 引脚尖 → 电气网络。

规则（和 Proteus 一致）：**连接靠端点重合，不靠相交**。
所以先做**空间聚类**（容差内视为同一点），再按聚类 id 连通 ——
不能拿浮点坐标直接比相等，0.5px 的差会把两条线断成两个网。

流程：
  1. 收集所有点：线段端点、结点、引脚尖
  2. 空间聚类（|dx|<=tol 且 |dy|<=tol 归为一类）
  3. 线段在结点处切开（结点投影到线段上），相邻切点构成一段
  4. 每段把两个端点的聚类 id 并起来
  5. 引脚尖所在的聚类 id 就是它所属的网
"""
from collections import defaultdict


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _cluster(points, tol):
    """返回 (聚类 id 列表, 每类代表坐标)"""
    uf = _UF(len(points))
    for i in range(len(points)):
        xi, yi = points[i]
        for j in range(i + 1, len(points)):
            xj, yj = points[j]
            if abs(xi - xj) <= tol and abs(yi - yj) <= tol:
                uf.union(i, j)
    ids = [uf.find(i) for i in range(len(points))]
    # 重编号 0..k
    remap = {}
    for i in ids:
        remap.setdefault(i, len(remap))
    ids = [remap[i] for i in ids]
    cent = defaultdict(list)
    for idx, (x, y) in enumerate(points):
        cent[ids[idx]].append((x, y))
    reps = {k: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v))
            for k, v in cent.items()}
    return ids, reps


def _project(jx, jy, seg, tol):
    """把结点投影到线段上；不在线段范围内返回 None"""
    (x1, y1), (x2, y2) = seg["a"], seg["b"]
    if abs(y1 - y2) <= tol:                       # 水平
        if abs(jy - y1) <= tol and min(x1, x2) - tol <= jx <= max(x1, x2) + tol:
            return (jx, y1)
    elif abs(x1 - x2) <= tol:                     # 竖直
        if abs(jx - x1) <= tol and min(y1, y2) - tol <= jy <= max(y1, y2) + tol:
            return (x1, jy)
    return None


def trace(segments, junctions, pin_tips, tol=3.0, exclude_boxes=()):
    """返回 {"nets":[...], "unresolved":[...]}

    segments:      [{"a":(x,y), "b":(x,y)}]
    junctions:     [{"x":..,"y":..}]
    pin_tips:      [{"ref":..,"pin":..,"tip":(x,y)}]
    exclude_boxes: [(x0,y0,x1,y1)] 器件本体包围盒。
                   盒内的线段是器件图形（矩形边框、圆弧），必须丢弃 ——
                   否则电阻的矩形边框会把它的两端短接。
    """
    boxes = [tuple(b) for b in exclude_boxes]
    pins_xy = [tuple(p["tip"]) for p in pin_tips]

    def inside(pt):
        x, y = pt
        return any(b[0] - 1 <= x <= b[2] + 1 and b[1] - 1 <= y <= b[3] + 1 for b in boxes)

    def at_pin(pt):
        # 容差要**紧**（1px）：本体侧边常常离引脚尖只差 2~3px，
        # 用 tol 会把它误判成"接在引脚上的引线"，于是短接器件两端。
        x, y = pt
        return any(abs(x - px) <= 1.0 and abs(y - py) <= 1.0 for px, py in pins_xy)

    # 器件本体图形（矩形边框、圆弧）不能当导线；但如果这条线段是接在引脚上的，
    # 它可能是真正的引线 —— 判据是"两端都在盒内、且都不接引脚"才丢。
    segments = [s for s in segments
                if not (inside(s["a"]) and inside(s["b"])
                        and not at_pin(s["a"]) and not at_pin(s["b"]))]

    points, tags = [], []

    def add(pt, tag):
        points.append(pt)
        tags.append(tag)

    for si, seg in enumerate(segments):
        add(seg["a"], ("seg", si))
        add(seg["b"], ("seg", si))
    for j in junctions:
        add((j["x"], j["y"]), ("junc", None))
    for p in pin_tips:
        add(tuple(p["tip"]), ("pin", (p["ref"], p["pin"])))

    ids, reps = _cluster(points, tol)
    seg_pt = defaultdict(list)                    # seg 索引 -> [(聚类 id, 坐标)]
    pin_pt = {}
    junc_pt = []                                  # [(聚类 id, 坐标)]
    for (pt, tag, cid) in zip(points, tags, ids):
        kind, val = tag
        if kind == "seg":
            seg_pt[val].append((cid, pt))
        elif kind == "pin":
            pin_pt[val] = cid
        elif kind == "junc":
            junc_pt.append((cid, pt))

    uf = _UF(max(ids) + 1)
    pieces = 0
    for si, seg in enumerate(segments):
        cuts = list(seg_pt[si])
        # 结点投影到这条线段上 → 用结点自己的聚类 id 作切点
        for cid, jpt in junc_pt:
            proj = _project(jpt[0], jpt[1], seg, tol)
            if proj is not None:
                cuts.append((cid, proj))
        uniq, seen = [], set()
        for cid, pt in cuts:
            if cid not in seen:
                seen.add(cid)
                uniq.append((cid, pt))
        if seg["a"][1] == seg["b"][1]:
            uniq.sort(key=lambda c: c[1][0])
        else:
            uniq.sort(key=lambda c: c[1][1])
        for (a, _), (b, _) in zip(uniq, uniq[1:]):
            uf.union(a, b)
            pieces += 1

    groups = defaultdict(set)
    used = set()
    for p in pin_tips:
        key = (p["ref"], p["pin"])
        cid = pin_pt.get(key)
        if cid is None:
            continue
        groups[uf.find(cid)].add(key)
        used.add(key)

    nets = [{"pins": sorted(v)} for v in groups.values() if len(v) >= 2]
    unresolved = [{"kind": "single_pin_net", "pin": sorted(v)[0]}
                  for v in groups.values() if len(v) == 1]
    return {"nets": nets, "unresolved": unresolved,
            "pieces": pieces, "nodes": max(ids) + 1}
