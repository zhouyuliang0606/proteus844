"""符号吸附 v2：直接在框附近搜索，要求"一个端点只能被一根引脚用"。

v1 的毛病：用全局投票，290 条线段产生大量巧合端点，
两根引脚的器件（电阻）在哪都能凑满 2/2，于是"满分却全错"。

v2 改法：
  · 锚点只在 bbox 中心附近 ±2 格内搜（用户给的框本来就定位了器件）
  · 一个观测端点只能被一根引脚占用（贪心分配），杜绝"一脚多投"
  · 目标函数 = 命中脚数，平手时比总误差
"""
import os
import sys

GRID_NATIVE = 254000


def _symbol_pins(donor, device):
    from proteus844.route.plan import _symbol_pins as SP
    raw = SP(donor, device)
    return {k: (v[0], v[1]) for k, v in raw.items()}


def _rot(dx, dy, angle):
    a = int(angle) % 360
    return {0: (dx, dy), 90: (-dy, dx), 180: (-dx, -dy), 270: (dy, -dx)}[a]


def endpoints_of(segs):
    pts = set()
    for s in segs:
        for p in (s["a"], s["b"]):
            pts.add((round(float(p[0]), 2), round(float(p[1]), 2)))
    return list(pts)


def _grid_index(pts, cell=4.0):
    idx = {}
    for p in pts:
        idx.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(p)
    return idx, cell


def _near(idx, cell, p, tol):
    cx, cy = int(p[0] // cell), int(p[1] // cell)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            out += idx.get((cx + dx, cy + dy), [])
    return [(q, ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5) for q in out]


def fit(segs, bbox, device, donor, ppg=None, ppg_span=(0.8, 1.25), tol=2.5, search_grids=2.0):
    pins = _symbol_pins(donor, device)
    if not pins:
        return {"ok": False, "reason": f"donor 无 {device}", "device": device}
    pts = endpoints_of(segs)
    idx, cell = _grid_index(pts)
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    if ppg is None:
        w = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
        span = max(max(abs(dx), abs(dy)) for dx, dy in pins.values()) or 1
        ppg = max(2.0, w / (2 * span))

    best = None
    ratios = [ppg * (ppg_span[0] + i * 0.025) for i in range(
        int((ppg_span[1] - ppg_span[0]) / 0.025) + 1)]
    for rot in (0, 90, 180, 270):
        offs = [(name,) + _rot(dx, dy, rot) for name, (dx, dy) in pins.items()]
        for g in ratios:
            R = search_grids * g
            step = max(1.0, g / 4)
            n = int(2 * R / step) + 1
            for i in range(n):
                for j in range(n):
                    ax = cx - R + i * step
                    ay = cy - R + j * step
                    used, hit, err = set(), 0, 0.0
                    for name, odx, ody in offs:
                        px, py = ax + odx * g, ay - ody * g
                        cands = sorted(_near(idx, cell, (px, py), tol), key=lambda t: t[1])
                        for q, d in cands:
                            if q in used or d > tol:
                                continue
                            used.add(q)
                            hit += 1
                            err += d
                            break
                    if hit == 0:
                        continue
                    # 几何先验：预测引脚包围盒必须和用户给的框对得上
                    xs = [ax + odx * g for _, odx, ody in offs]
                    ys = [ay - ody * g for _, odx, ody in offs]
                    pw, ph = max(xs) - min(xs), max(ys) - min(ys)
                    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    pcx, pcy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
                    center_off = (((pcx - cx) ** 2 + (pcy - cy) ** 2) ** 0.5) / g
                    size_off = (abs(pw - bw) + abs(ph - bh)) / (2 * g)
                    penalty = center_off + size_off
                    key = (hit - 0.5 * penalty, -err)
                    if best is None or key > best[0]:
                        best = (key, rot, g, ax, ay, hit, err)

    if best is None:
        return {"ok": False, "reason": "无候选", "device": device}
    _, rot, g, ax, ay, hit, err = best
    offs = [(name,) + _rot(dx, dy, rot) for name, (dx, dy) in pins.items()]
    used, detail = set(), {}
    for name, odx, ody in offs:
        px, py = ax + odx * g, ay - ody * g
        cands = sorted(_near(idx, cell, (px, py), tol), key=lambda t: t[1])
        got = None
        for q, d in cands:
            if q in used or d > tol:
                continue
            used.add(q)
            got = (q, d)
            break
        detail[name] = {"px": (round(px, 1), round(py, 1)),
                        "matched": got is not None,
                        "dist": round(got[1], 2) if got else None,
                        "snapped_to": got[0] if got else None}
    return {"ok": True, "device": device,
            "anchor_px": (round(ax, 1), round(ay, 1)), "rotation": rot,
            "px_per_grid": round(g, 3), "score": round(hit / len(offs), 3),
            "matched": hit, "total": len(offs), "pins": detail}
