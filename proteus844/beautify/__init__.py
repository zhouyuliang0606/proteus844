"""画图美观：居中 / 体检 / 打分。

设计完（布局 + 布线都有了坐标）之后、写文件之前，过一遍这里：

    doc = beautify.center(doc, donor)      # 把整张图挪到图纸正中
    print(beautify.review(doc, donor))     # 体检报告：留白、越界、交叉、绕线

为什么需要单独一层：布局只管"信号从左到右"，不管"整块摆在纸的哪个位置"。
Proteus 的页框以 (0,0) 为中心，所以必须显式对齐，否则整块会贴到某个角上。

单位：格（grid = 100 mil = 254000 native）。
"""
import collections

GRID = 254000

# 器件符号本体的粗略外扩：引脚位置之外还要留出封装轮廓
SYMBOL_PAD = 3.0


def _pins(donor, device):
    from ..route.plan import _symbol_pins
    return _symbol_pins(donor, device)


def _rot(dx, dy, ddx, ddy, ang):
    a = int(ang) % 360
    if a == 0:
        return dx, dy, ddx, ddy
    if a == 90:
        return -dy, dx, -ddy, ddx
    if a == 180:
        return -dx, -dy, -ddx, -ddy
    return dy, -dx, ddy, -ddx


def component_extent(comp, donor):
    """器件的实际占位（含符号本体），返回 (x0, y0, x1, y1) 格。"""
    ang = int(comp.get("rotation", 0))
    cx, cy = float(comp["x"]), float(comp["y"])
    try:
        pins = _pins(donor, comp["device"])
    except Exception:
        pins = {}
    xs, ys = [0.0], [0.0]
    for name, v in pins.items():
        dx, dy, ddx, ddy = _rot(*v, ang)
        xs.append(dx)
        ys.append(dy)
    return (cx + min(xs) - SYMBOL_PAD, cy + min(ys) - SYMBOL_PAD,
            cx + max(xs) + SYMBOL_PAD, cy + max(ys) + SYMBOL_PAD)


def bbox(doc, donor, with_wires=True):
    """整张图的实际外框（器件本体 + 所有导线顶点），单位格。"""
    xs, ys = [], []
    for c in doc.get("components") or []:
        if "x" not in c or "y" not in c:
            continue
        x0, y0, x1, y1 = component_extent(c, donor)
        xs += [x0, x1]
        ys += [y0, y1]
    if with_wires:
        for n in doc.get("nets") or []:
            pts = list(n.get("path") or [])
            for b in n.get("branches") or []:
                pts += list(b.get("points") or [])
            for p in pts:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def center(doc, donor, target=(0.0, 0.0)):
    """把整张图平移到 target（默认图纸中心）。返回 (dx, dy)。"""
    box = bbox(doc, donor)
    if box is None:
        return (0.0, 0.0)
    x0, y0, x1, y1 = box
    dx = round(target[0] - (x0 + x1) / 2, 1)
    dy = round(target[1] - (y0 + y1) / 2, 1)
    if dx == 0 and dy == 0:
        return (0.0, 0.0)
    for c in doc.get("components") or []:
        if "x" in c and "y" in c:
            c["x"] = round(float(c["x"]) + dx, 1)
            c["y"] = round(float(c["y"]) + dy, 1)
    for n in doc.get("nets") or []:
        if n.get("path"):
            n["path"] = [[round(p[0] + dx, 1), round(p[1] + dy, 1)] for p in n["path"]]
        for b in n.get("branches") or []:
            b["points"] = [[round(p[0] + dx, 1), round(p[1] + dy, 1)] for p in b["points"]]
        if n.get("junction"):
            n["junction"] = [round(n["junction"][0] + dx, 1),
                             round(n["junction"][1] + dy, 1)]
    if doc.get("terminals"):
        for t in doc["terminals"]:
            if isinstance(t.get("position"), (list, tuple)):
                t["position"] = [round(t["position"][0] + dx, 1),
                                 round(t["position"][1] + dy, 1)]
    return (dx, dy)


# ---------- 体检 ----------

def _seg_len(p, q):
    return abs(p[0] - q[0]) + abs(p[1] - q[1])


def review(doc, donor, sheet=(100.0, 70.0)):
    """给一张画好的图做体检，返回可直接打印/判断的字典。

    回答的问题：
      - 整块在不在纸里？四边留白多少？
      - 摆得正不正？上下左右是否失衡？
      - 线走得绕不绕？总长 / 最少需要的长度
      - 有没有跨网共线（看着像连在一起）？
    """
    box = bbox(doc, donor)
    if box is None:
        return {"ok": False, "reason": "没有可测量的几何"}
    x0, y0, x1, y1 = box
    hw, hh = sheet[0] / 2, sheet[1] / 2
    margins = {"left": x0 + hw, "right": hw - x1, "bottom": y0 + hh, "top": hh - y1}
    outside = [k for k, v in margins.items() if v < 0]

    total = 0.0
    segs = collections.defaultdict(list)      # 用于查共线
    for n in doc.get("nets") or []:
        paths = [n["path"]] if n.get("path") else [b["points"] for b in n.get("branches") or []]
        for pts in paths:
            for a, b in zip(pts, pts[1:]):
                total += _seg_len(a, b)
                if a[1] == b[1]:
                    segs[("h", a[1])].append((min(a[0], b[0]), max(a[0], b[0]), n.get("name")))
                elif a[0] == b[0]:
                    segs[("v", a[0])].append((min(a[1], b[1]), max(a[1], b[1]), n.get("name")))

    overlaps = 0
    for key, items in segs.items():
        items.sort()
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                lo1, hi1, n1 = items[i]
                lo2, hi2, n2 = items[j]
                if n1 == n2:
                    continue
                if min(hi1, hi2) - max(lo1, lo2) > 0:
                    overlaps += 1

    # 最少需要的长度：每个网从最左引脚到最右引脚
    need = 0.0
    for n in doc.get("nets") or []:
        pts = list(n.get("path") or [])
        for b in n.get("branches") or []:
            pts += list(b.get("points") or [])
        if len(pts) >= 2:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            need += (max(xs) - min(xs)) + (max(ys) - min(ys))
    detour = round(total / need, 2) if need else 1.0

    w, d = (x1 - x0), (y1 - y0)
    fill_x = round(w / sheet[0], 2)
    fill_y = round(d / sheet[1], 2)
    off_x = round(((x0 + x1) / 2), 1)
    off_y = round(((y0 + y1) / 2), 1)

    problems = []
    if outside:
        problems.append(f"越出图纸：{outside}")
    if abs(off_x) > 1 or abs(off_y) > 1:
        problems.append(f"没摆正：偏离中心 ({off_x:+.1f}, {off_y:+.1f}) 格")
    if min(margins.values()) < 2:
        problems.append(f"留白不足：最小 {min(margins.values()):.1f} 格")
    if overlaps:
        problems.append(f"跨网共线 {overlaps} 处（看着像连在一起）")
    if detour > 1.8:
        problems.append(f"绕线偏多：总长是最短需求的 {detour} 倍")

    return {"ok": not problems, "problems": problems, "bbox": box,
            "margins": {k: round(v, 1) for k, v in margins.items()},
            "offset": (off_x, off_y), "size": (round(w, 1), round(d, 1)),
            "fill": (fill_x, fill_y), "wire_length": round(total, 1),
            "detour_ratio": detour, "cross_net_overlaps": overlaps,
            "score": _score(problems, fill_x, fill_y, detour, overlaps)}


def _score(problems, fill_x, fill_y, detour, overlaps):
    """0~100 的观感分。分项扣，不追求精确，只要能横向比较两版哪版更好。"""
    s = 100.0
    s -= 20 * len(problems)
    if fill_x < 0.25 or fill_y < 0.25:
        s -= 10                       # 太空
    if fill_x > 0.95 or fill_y > 0.95:
        s -= 10                       # 太满
    s -= min(15.0, (detour - 1.0) * 20) if detour > 1.0 else 0
    s -= min(10.0, overlaps * 2)
    return max(0, round(s))


def format_review(r):
    if not r.get("bbox"):
        return "无法测量"
    lines = [f"外框 {r['size'][0]:.0f}×{r['size'][1]:.0f} 格，"
             f"占纸 {r['fill'][0]:.0%}×{r['fill'][1]:.0%}，观感分 {r['score']}/100"]
    m = r["margins"]
    lines.append(f"  留白 左{m['left']:.0f} 右{m['right']:.0f} 上{m['top']:.0f} 下{m['bottom']:.0f}")
    lines.append(f"  偏移 {r['offset'][0]:+.1f}, {r['offset'][1]:+.1f} 格；"
                 f"绕线系数 {r['detour_ratio']}")
    if r["problems"]:
        for p in r["problems"]:
            lines.append(f"  ⚠ {p}")
    else:
        lines.append("  ✅ 居中、在纸内、无跨网共线、绕线正常")
    return "\n".join(lines)


# ---------- 对已经写好的工程做体检 ----------

def load_project(path, donor=None):
    """把 .pdsprj 读成一个 plan 形状的 doc，供 review() 使用。"""
    from ..verify import file_netlist as F
    from ..verify import reader as R

    recs, _ = R.parse(path)
    comps = []
    for r in recs:
        if not r.get("ref"):
            continue
        comps.append({"ref": r["ref"], "device": r["device"], "value": r.get("value"),
                      "x": r["x"] / GRID, "y": r["y"] / GRID,
                      "rotation": r.get("rotation", 0)})
    _r, wires, _n, wire_net = F.rebuild(path, with_wire_net=True)
    nets = []
    for start, pts in wires.items():
        nets.append({"name": wire_net.get(start, "?"),
                     "path": [[p[0] / GRID, p[1] / GRID] for p in pts]})
    return {"components": comps, "nets": nets, "terminals": []}


def review_project(path, donor=None, sheet=None):
    """体检一个 .pdsprj，返回与 review() 相同结构的字典。"""
    from ..verify import sheet as S

    if sheet is None:
        s = S.read_sheet(path) or {}
        sheet = (s.get("width_grids", 100.0), s.get("height_grids", 70.0))
    doc = load_project(path, donor)
    if donor is None:
        # 没有 donor 就用 default 的引脚估算：只按器件锚点 + pad
        for c in doc["components"]:
            c["_no_pins"] = True
    try:
        return review(doc, donor, sheet=sheet)
    except Exception:
        # donor 不可用时退化：只按锚点算外框
        xs = [c["x"] for c in doc["components"]]
        ys = [c["y"] for c in doc["components"]]
        if not xs:
            return {"ok": False, "reason": "无法读取器件"}
        return review({"components": [dict(c, device="") for c in doc["components"]],
                       "nets": doc["nets"]}, donor, sheet=sheet)
