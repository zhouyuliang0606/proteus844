"""从「器件框 + 型号」自动推引脚 —— v2，只认"悬空端点"。

核心：器件引脚在图上的特征是 **一根导线的尽头，且该点只连着一根线**（degree=1）。
其它端点都连着两根线，是导线内部的拐点，不是引脚。

比例差异不影响判定：引脚在符号的哪一侧、该侧第几个，跨库是一致的。
"""
import collections

GRID = 4.8          # 仅用于"多近算贴着这个器件"


SUPPLY = {"VCC", "VDD", "GND", "VSS", "VEE", "+5V", "+3V3", "GNDA"}


def _symbol_sides(donor, device):
    """{引脚名: (side, index)}。

    侧别按**引脚朝向**判（dir），不是按偏移量 —— 偏移量会被电源脚带偏。
    VCC/GND 这类隐藏电源脚不参与：它们在图上是画不出来的，永远没有导线连着。
    """
    from proteus844.route.plan import _symbol_pins
    raw = _symbol_pins(donor, device)
    groups = collections.defaultdict(dict)
    for name, (dx, dy, ddx, ddy) in raw.items():
        if name.upper() in SUPPLY:
            continue
        if ddx < 0:
            side, key = "L", -dy
        elif ddx > 0:
            side, key = "R", -dy
        elif ddy > 0:
            side, key = "T", dx
        elif ddy < 0:
            side, key = "B", dx
        else:
            side, key = ("L" if dx < 0 else "R"), -dy
        groups[side][name] = key
    out = {}
    for side, members in groups.items():
        for i, (name, _) in enumerate(sorted(members.items(), key=lambda kv: kv[1])):
            out[name] = (side, i)
    return out


def degrees(segs):
    """每个线段端点连了几根线"""
    deg = collections.Counter()
    for s in segs:
        for p in (s["a"], s["b"]):
            deg[(round(float(p[0]), 2), round(float(p[1]), 2))] += 1
    return deg


def dangling_points(segs):
    return [p for p, d in degrees(segs).items() if d == 1]


def _dist_to_box(p, bbox):
    x0, y0, x1, y1 = bbox
    dx = max(x0 - p[0], 0, p[0] - x1)
    dy = max(y0 - p[1], 0, p[1] - y1)
    return (dx * dx + dy * dy) ** 0.5


def pins_from_box(segs, bbox, device, donor, reach=None, other_boxes=()):
    """返回 {ok, pins, unmatched, notes}；pins 是 {引脚名: (x, y)} 像素坐标"""
    if reach is None:
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        reach = max(12.0, 0.45 * max(w, h))
    sides = _symbol_sides(donor, device)
    cands = dangling_points(segs)

    mine = []
    for p in cands:
        d = _dist_to_box(p, bbox)
        if d > reach:
            continue
        # 别的器件更近就归别人
        others = [_dist_to_box(p, b) for b in other_boxes if b is not bbox]
        if others and min(others) < d:
            continue
        mine.append(p)

    x0, y0, x1, y1 = bbox
    edge_reach = max(10.0, 0.30 * min(max(1.0, x1 - x0), max(1.0, y1 - y0)))
    by_side = collections.defaultdict(list)
    for p in mine:
        # 按"离哪条边最近"归类，超出边缘容差就丢掉
        cand = []
        if y0 - edge_reach <= p[1] <= y1 + edge_reach:
            cand.append((abs(p[0] - x0), "L"))
            cand.append((abs(p[0] - x1), "R"))
        if x0 - edge_reach <= p[0] <= x1 + edge_reach:
            cand.append((abs(p[1] - y0), "T"))
            cand.append((abs(p[1] - y1), "B"))
        if not cand:
            continue
        d, side = min(cand)
        if d <= edge_reach:
            by_side[side].append(p)

    want = collections.defaultdict(list)
    for name, (side, idx) in sides.items():
        want[side].append((idx, name))

    pins, unmatched, notes = {}, [], []
    for side in set(list(want) + list(by_side)):
        w = [n for _, n in sorted(want.get(side, []))]
        got = by_side.get(side, [])
        got.sort(key=lambda p: p[1] if side in ("L", "R") else p[0])
        if len(got) == len(w):
            for name, p in zip(w, got):
                pins[name] = (round(p[0], 1), round(p[1], 1))
        else:
            notes.append(f"{side}: 符号 {len(w)} 脚 / 图上 {len(got)} 个悬空端点")
            unmatched += w
    return {"ok": not unmatched and len(pins) == len(sides),
            "device": device, "pins": pins, "unmatched": unmatched,
            "notes": notes, "dangling_found": len(mine)}


# ===========================================================================
# 引脚桩判据（辅助，不是主手段）
#
# 引脚桩 = 「一端贴着器件框、方向垂直于该边、长度很短」的线段，外端就是引脚尖。
# 实测：对画了引脚桩的符号很准（74147 拿到 13/13），
#       但同一张图上别的符号（电阻/7430/数码管）导线直接顶到本体，没有独立桩 → 0 命中。
# 所以它只能当"这块器件的引脚是不是这样"的提示，覆盖不全。
# ===========================================================================
def stub_pins(segs, bbox, max_len=14.0, touch=2.5):
    x0, y0, x1, y1 = bbox
    found = []
    for g in segs:
        ax, ay = g["a"]
        bx, by = g["b"]
        L = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        if not (1.0 <= L <= max_len):
            continue
        if not (abs(ay - by) <= 1.5 or abs(ax - bx) <= 1.5):
            continue
        for (p, q) in (((ax, ay), (bx, by)), ((bx, by), (ax, ay))):
            on_edge = ((abs(p[0] - x0) <= touch and y0 - touch <= p[1] <= y1 + touch)
                       or (abs(p[0] - x1) <= touch and y0 - touch <= p[1] <= y1 + touch)
                       or (abs(p[1] - y0) <= touch and x0 - touch <= p[0] <= x1 + touch)
                       or (abs(p[1] - y1) <= touch and x0 - touch <= p[0] <= x1 + touch))
            outside = (q[0] < x0 - touch or q[0] > x1 + touch
                       or q[1] < y0 - touch or q[1] > y1 + touch)
            if on_edge and outside:
                found.append(q)
                break
    return found


def coverage(segs, bbox, device, donor):
    """这根器件的桩能覆盖多少脚 —— 低于符号脚数就说明不可靠，别用"""
    import collections as _c
    sides = _symbol_sides(donor, device)
    need = _c.Counter(s for s, _ in sides.values())
    got = stub_pins(segs, bbox)
    return {"stubs": len(got), "need": sum(need.values()),
            "per_side": dict(need), "usable": len(got) == sum(need.values())}
