"""测「只给器件框和型号，自动推引脚」的准确率。

⚠ 这是**负面实验记录**，不是通过的测试：结论是这条路走不通，
数字留档供以后参考。修改后请保持 exit 0。

基准 = tests/encoder_components.json 里人工标的引脚像素坐标。
这次不要求像素级贴合（符号比例本来就不同），只要求**引脚落在对应的那条引线上**。
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.recognize import segments as S
from proteus844.recognize import pins_from_box as PB

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
    segs = S.as_segments(S.extract(np.array(im) < 140, min_len=6))
    boxes = [c["bbox"] for c in comps if c.get("bbox")]

    ok_dev = total_dev = 0
    pin_ok = pin_all = 0
    rows = []
    for c in comps:
        if not c.get("bbox"):
            continue
        r = PB.pins_from_box(segs, c["bbox"], c["device"], DONOR, other_boxes=boxes)
        total_dev += 1
        n_want = len(c["pins"])
        if r["ok"]:
            ok_dev += 1
        # 逐脚比对：自动推出的位置 vs 人工标的，容差 1 格（4.8px）
        good = 0
        truth = c["pins"]
        for name, (gx, gy) in truth.items():
            p = r["pins"].get(name)
            if not p:
                pin_all += 1
                continue
            d = ((p[0] - gx) ** 2 + (p[1] - gy) ** 2) ** 0.5
            pin_all += 1
            if d <= 4.8:
                good += 1
                pin_ok += 1
        rows.append((c["ref"], c["device"], r["ok"], good, len(truth), r["notes"][:1]))

    print(f"{'器件':10} {'型号':18} {'配齐':>4} {'落点对':>7}")
    for ref, dev, ok, good, n, note in rows:
        mark = "✅" if ok else "⚠"
        print(f"{ref:10} {dev:18} {mark:>4} {good:>3}/{n:<3} {note[0] if note else ''}")
    print(f"\n器件级：引脚全部配齐 {ok_dev}/{total_dev} = {100*ok_dev/max(1,total_dev):.0f}%")
    print(f"引脚级：落在对应引线上（±1 格） {pin_ok}/{pin_all} = {100*pin_ok/max(1,pin_all):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
