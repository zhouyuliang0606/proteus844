"""引脚预测：由「器件 + 一个已知引脚尖」推出全部引脚尖的像素坐标。

用法（给识别用）：
    模型只需指着**任意一个**引脚尖说"这是 U1:D 的 Y 脚，在这"，
    剩下的引脚由符号定义算出来 —— 不用逐个在图上点。

    tips = predict(components, donor, px_per_grid)

components: [{"ref":"U1:D","device":"7400","pin":"Y","tip_px":[150,26]}]
"""


def _symbol_pins(donor, device):
    """从 donor 读出某个型号的 {引脚名: (dx,dy)}（单位：格），带缓存。"""
    cache = getattr(_symbol_pins, "_cache", None)
    if cache is None:
        cache = _symbol_pins._cache = {}
    key = (donor, device)
    if key in cache:
        return cache[key]
    import sys
    sys.path.insert(0, _vendor_dir())
    from component_codec import Circuit
    c = Circuit(donor)
    ref = "P1:A"
    c.add(device=device, ref=ref, value=device, x=0, y=0)
    G = 254000
    pins = {p["name"]: (p["position"][0] / G, p["position"][1] / G)
            for p in c.pins(ref)}
    cache[key] = pins
    return pins


def _vendor_dir():
    import os
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "vendor", "ref844")


def predict(components, donor, px_per_grid):
    """返回 [{ref, device, anchor_px, pins:{name:(x,y)}}]"""
    out = []
    for comp in components:
        pins = _symbol_pins(donor, comp["device"])
        known = comp.get("pin")
        if known is None:
            raise ValueError(f"{comp['ref']} 需要给出至少一个已知引脚（pin + tip_px）")
        if known not in pins:
            raise ValueError(f"{comp['device']} 没有引脚 {known!r}，实际有 {sorted(pins)}")
        kx, ky = pins[known]
        tx, ty = comp["tip_px"]
        ax, ay = tx - kx * px_per_grid, ty - ky * px_per_grid
        out.append({
            "ref": comp["ref"], "device": comp["device"],
            "anchor_px": (ax, ay),
            "pins": {name: (ax + dx * px_per_grid, ay + dy * px_per_grid)
                     for name, (dx, dy) in pins.items()},
        })
    return out


def snap_to_ink(tips, ink, radius=2):
    """把预测的引脚尖吸附到附近的墨迹上（修正 1~2px 比例误差）。"""
    import numpy as np
    out = []
    h, w = ink.shape
    for comp in tips:
        moved = {}
        for name, (x, y) in comp["pins"].items():
            ix, iy = int(round(x)), int(round(y))
            best, bestd = (x, y), None
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    px, py = ix + dx, iy + dy
                    if 0 <= py < h and 0 <= px < w and ink[py, px]:
                        d = dx * dx + dy * dy
                        if bestd is None or d < bestd:
                            best, bestd = (float(px), float(py)), d
            moved[name] = best
        out.append(dict(comp, pins=moved))
    return out
