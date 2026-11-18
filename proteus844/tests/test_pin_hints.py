"""pin_hints 的验收：放大标注表里必须真的能覆盖到引脚。

基准：编码器 22 器件 / 80 个真引脚。要求覆盖率 ≥ 70%（实测 75%）。
剩下 25% 主要是本来就没接线的引脚（如 74147 的 Q3）和抽取缺口。
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.recognize import hints as H
from proteus844.recognize import preprocess as PP
from proteus844.recognize import segments as S

from proteus844.tests import _img
IMG = _img.source_image()
COMPS = os.path.join(HERE, "tests", "encoder_components.json")
OUT = os.path.join(os.environ.get("TEMP", "."), "_hint_check.png")


def main():
    if IMG is None:
        _img.need_image(__name__)
        return 0
    comps = json.load(open(COMPS, encoding="utf-8-sig"))
    gray = np.array(Image.open(IMG).convert("L"))
    ink, th, dropped = PP.wire_mask(gray)
    segs = S.as_segments(S.extract(ink, min_len=3))
    print(f"预处理：阈值 {th} / 去文字 {dropped} 块 / 线段 {len(segs)}")

    tot = hit = 0
    worst = []
    for c in comps:
        r = H.annotate(IMG, segs, c["bbox"], OUT, scale=3, max_points=80)
        pts = [tuple(v) for v in r["points"].values()]
        h = 0
        for name, (gx, gy) in c["pins"].items():
            tot += 1
            if any(abs(p[0] - gx) <= 1.0 and abs(p[1] - gy) <= 1.0 for p in pts):
                hit += 1
                h += 1
        if h < len(c["pins"]):
            worst.append(f"{c['ref']} {h}/{len(c['pins'])}")

    rate = 100 * hit / max(1, tot)
    print(f"覆盖：{hit}/{tot} = {rate:.1f}%")
    print(f"没覆盖全的器件：{', '.join(worst[:8])}{' …' if len(worst) > 8 else ''}")

    # 产物可用性：PNG 真的写出来了、编号表非空
    ok_png = os.path.exists(OUT) and os.path.getsize(OUT) > 1000
    r = H.annotate(IMG, segs, comps[0]["bbox"], OUT, scale=4)
    ok_table = r["count"] > 0 and len(r["points"]) == r["count"]
    print(f"PNG 产出 {ok_png} / 编号表 {ok_table}（{r['count']} 个端点）")
    return 0 if (rate >= 70 and ok_png and ok_table) else 1


if __name__ == "__main__":
    sys.exit(main())
