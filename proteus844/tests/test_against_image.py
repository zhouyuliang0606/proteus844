"""「对着图初筛」的验收：本地校验必须能抓错，且真实网络要基本干净。

定位：这是初筛，不是判据。已知编码器图里 N1..N6 六条开关网会被标红 ——
那是**真的**（原图是三端 SPDT，网表里 COM 的位置和图上对不上），不是误报。
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.recognize import preprocess as PP
from proteus844.recognize import segments as S
from proteus844.verify import against_image as A

from proteus844.tests import _img
IMG = _img.source_image()
COMPS = os.path.join(HERE, "tests", "encoder_components.json")
NETS = os.path.join(HERE, "tests", "encoder_netlist.json")

KNOWN_SUSPECT = {"N1", "N2", "N3", "N4", "N5", "N6"}   # 开关网：原图 SPDT 对不上


def main():
    if IMG is None:
        _img.need_image(__name__)
        return 0
    comps = json.load(open(COMPS, encoding="utf-8-sig"))
    nets = json.load(open(NETS, encoding="utf-8-sig"))["nets"]
    gray = np.array(Image.open(IMG).convert("L"))
    ink, th, dropped = PP.wire_mask(gray, base=140, max_glyph=11, min_extent=14)
    segs = S.as_segments(S.extract(ink, min_len=6))
    print(f"预处理：Otsu 阈值 {th}，去掉 {dropped} 个文字块，{len(segs)} 条线段")
    print(f"线段 {len(segs)} / 器件 {len(comps)} / 网 {len(nets)}\n")

    # ===== 正样本 =====
    r = A.check_local(comps, nets, segs)
    flagged = {p["net"] for p in r["problems"]}
    clean = len([n for n in nets if (n.get("name") or "").upper() not in A.SUPPLY]) - len(flagged)
    print(f"[正样本] {r['summary']}   干净 {clean}/28")
    extra = flagged - KNOWN_SUSPECT
    if extra:
        print(f"   额外报出（需人工确认）：{sorted(extra)}")

    # ===== 反样本 =====
    # 真实的识别错误：两条网各有一个脚张冠李戴
    bad = []
    for n in nets:
        m = dict(n)
        if n["name"] == "N20":
            m["pins"] = [["R1", "1"]] + n["pins"][1:]
        elif n["name"] == "N19":
            m["pins"] = [["R2", "1"]] + n["pins"][1:]
        bad.append(m)
    r1 = A.check_local(comps, bad, segs)
    caught1 = len([p for p in r1["problems"] if p["net"] in ("N19", "N20")]) >= 1

    bad2 = []
    for n in nets:
        if n["name"] == "N20" and len(n["pins"]) >= 2:
            bad2.append({"name": "N20a", "pins": n["pins"][:1]})
            bad2.append({"name": "N20b", "pins": n["pins"][1:]})
        else:
            bad2.append(n)
    r2 = A.check_local(comps, bad2, segs)
    caught2 = any(p["net"] == "N20a" and p["type"] == "SINGLE_PIN" for p in r2["problems"])

    badc = json.loads(json.dumps(comps))
    for c in badc:
        if c["ref"] == "R3" and "1" in c["pins"]:
            c["pins"]["1"] = [c["pins"]["1"][0] - 40, c["pins"]["1"][1] - 40]
    r3 = A.check_local(badc, nets, segs)
    caught3 = any(p["type"] == "UNCONNECTED_PIN" for p in r3["problems"])

    print(f"\n[反样本1] 引脚张冠李戴 → {'✅ 抓到' if caught1 else '⚠ 已知盲点：密集扇出区会滑过'}")
    print(f"[反样本2] 真网拆成两半 → {'✅ 抓到' if caught2 else '❌ 漏了'}")
    print(f"[反样本3] 引脚坐标挪 40px → {'✅ 抓到' if caught3 else '❌ 漏了'}")
    print(f"\n基线：28 条网里干净 {clean} 条，已知可疑 {sorted(flagged & KNOWN_SUSPECT)}")
    # 反样本 1 是已知盲点，不作硬性断言；2、3 必须抓到
    return 0 if (caught2 and caught3 and not extra) else 1


if __name__ == "__main__":
    sys.exit(main())
