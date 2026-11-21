"""布线度量：把"线乱不乱"变成数字。

四个指标：
  crossings   交叉 —— 横线和竖线在非端点处相交。读者要判断"这里到底连没连"，
              是最伤可读性的东西。
  overlaps    跨网共线 —— 两段不同网的线画在同一条直线上，看着像连在一起。
  detour      绕线系数 —— 实际总长 ÷ 每网最短需求。
  bends       拐弯总数 —— 每多一个拐弯，读的人多一次判断。

用法：
    from proteus844.route import metrics
    m = metrics.measure(doc)
    print(metrics.format_metrics(m))
"""
import collections


def _segs(doc):
    """把 plan 里的所有折线拆成线段：(网名, 方向, 固定坐标, 起, 止)"""
    out = []
    for n in doc.get("nets") or []:
        name = n.get("name") or "?"
        paths = []
        if n.get("path"):
            paths.append(n["path"])
        for b in n.get("branches") or []:
            paths.append(b["points"])
        for pts in paths:
            for a, b in zip(pts, pts[1:]):
                if a[1] == b[1]:
                    out.append((name, "h", a[1], min(a[0], b[0]), max(a[0], b[0])))
                elif a[0] == b[0]:
                    out.append((name, "v", a[0], min(a[1], b[1]), max(a[1], b[1])))
    return out


def _cross(a, b):
    """横线 a 与竖线 b 是否在非端点处相交。"""
    _, _, y, x0, x1 = a
    _, _, x, y0, y1 = b
    if not (x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6):
        return False
    # 端点不算交叉（那是 T 接或拐角）
    eps = 1e-6
    for px, py in ((x, y),):
        on_a_end = (abs(px - x0) < eps or abs(px - x1) < eps)
        on_b_end = (abs(py - y0) < eps or abs(py - y1) < eps)
        if on_a_end or on_b_end:
            return False
    return True


def measure(doc):
    segs = _segs(doc)
    hs = [s for s in segs if s[1] == "h"]
    vs = [s for s in segs if s[1] == "v"]

    crossings = 0
    cross_detail = []
    for h in hs:
        for v in vs:
            if h[0] == v[0]:
                continue
            if _cross(h, v):
                crossings += 1
                cross_detail.append(((h[0], v[0]), (round(v[2], 1), round(h[2], 1))))

    overlaps = 0
    by_fixed = collections.defaultdict(list)
    for s in segs:
        by_fixed[(s[1], s[2])].append(s)
    for _, items in by_fixed.items():
        items.sort(key=lambda s: s[3])
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a[0] == b[0]:
                    continue
                if min(a[4], b[4]) - max(a[3], b[3]) > 1e-6:
                    overlaps += 1

    total = sum(abs(s[4] - s[3]) for s in segs)
    bends = 0
    need = 0.0
    for n in doc.get("nets") or []:
        paths = []
        if n.get("path"):
            paths.append(n["path"])
        for b in n.get("branches") or []:
            paths.append(b["points"])
        for pts in paths:
            bends += max(0, len(pts) - 2)
            if len(pts) >= 2:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                need += (max(xs) - min(xs)) + (max(ys) - min(ys))

    return {
        "crossings": crossings,
        "overlaps": overlaps,
        "bends": bends,
        "segments": len(segs),
        "wire_length": round(total, 1),
        "needed": round(need, 1),
        "detour": round(total / need, 2) if need else 1.0,
        "cross_detail": cross_detail[:20],
    }


def format_metrics(m):
    return (f"线段 {m['segments']}  交叉 {m['crossings']}  跨网共线 {m['overlaps']}  "
            f"拐弯 {m['bends']}  绕线 {m['detour']}")


def penalty(m):
    """越小越好。用来在多种布法之间选。"""
    return (m["crossings"] * 3 + m["overlaps"] * 2 + m["bends"] * 0.5
            + (m["detour"] - 1.0) * 20)
