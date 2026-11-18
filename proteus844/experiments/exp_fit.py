"""用编码器图验证符号吸附：能不能自动还原我们手工量出来的 68 个引脚尖。

⚠ 这是**负面实验记录**，不是通过的测试：结论是这条路走不通，
数字留档供以后参考。修改后请保持 exit 0。

基准（ground truth）= tests/encoder_components.json 里人工标的引脚像素坐标。
指标：
  · 引脚定位准确率：拟合出的脚位与人工标的距离 ≤ 半格 / ≤ 1 格
  · 朝向正确率
  · 器件整体命中率（全部脚都对才算对）
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.recognize import segments as S
from proteus844.recognize import fit as FIT

from proteus844.tests import _img
IMG = _img.source_image()
DONOR = os.path.join(HERE, "donors", "kit.pdsprj")
COMPS = os.path.join(HERE, "tests", "encoder_components.json")


def main():
    if IMG is None:
        _img.need_image(__name__)
        return 0
    comps = json.load(open(COMPS, encoding="utf-8-sig"))
    im = Image.open(IMG).convert("L")
    ink = np.array(im) < 140
    segs = S.as_segments(S.extract(ink, min_len=6))
    print(f"线段 {len(segs)} 条，器件 {len(comps)} 个")

    # 用人工标定反推基准比例尺
    ppgs = []
    for c in comps:
        xy = c.get("pins") or {}
        if len(xy) < 2:
            continue
        dev = c["device"]
        try:
            offs = FIT._symbol_pins(DONOR, dev)
        except Exception:
            continue
        names = [n for n in xy if n in offs]
        if len(names) < 2:
            continue
        gx = max(offs[n][0] for n in names) - min(offs[n][0] for n in names)
        px = max(v[0] for v in xy.values()) - min(v[0] for v in xy.values())
        if gx > 0 and px > 0:
            ppgs.append(px / gx)
    base_ppg = float(np.median(ppgs)) if ppgs else 8.4
    print(f"基准 px_per_grid ≈ {base_ppg:.3f}")

    total_pins = hit_half = hit_one = 0
    perfect = 0
    rows = []
    for c in comps:
        xy = c.get("pins") or {}
        if not xy:
            continue
        r = FIT.fit(segs, c["bbox"], c["device"], DONOR, ppg=base_ppg)
        if not r.get("ok"):
            rows.append((c["ref"], c["device"], "失败", r.get("reason"), 0, 0))
            continue
        n = len(xy)
        h_half = h_one = 0
        for name, (gx, gy) in xy.items():
            p = r["pins"].get(name)
            if not p:
                continue
            d = ((p["px"][0] - gx) ** 2 + (p["px"][1] - gy) ** 2) ** 0.5
            if d <= base_ppg / 2:
                h_half += 1
            if d <= base_ppg:
                h_one += 1
        total_pins += n
        hit_half += h_half
        hit_one += h_one
        if h_half == n:
            perfect += 1
        rows.append((c["ref"], c["device"], r["rotation"], r["score"], h_half, n))

    print(f"\n{'器件':10} {'型号':18} {'朝向':>4} {'命中率':>6} {'≤半格':>7}")
    for ref, dev, rot, score, h, n in rows:
        print(f"{ref:10} {dev:18} {rot:>4} {score:>6} {h:>3}/{n:<3}")
    print(f"\n引脚级：≤半格 {hit_half}/{total_pins} = {100*hit_half/max(1,total_pins):.1f}%"
          f"   ≤1格 {hit_one}/{total_pins} = {100*hit_one/max(1,total_pins):.1f}%")
    print(f"器件级：全部脚 ≤半格 {perfect}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
