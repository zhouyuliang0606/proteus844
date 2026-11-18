"""识别校验（局部、可判定）：比对**每个引脚上导线离开的方向**。

为什么这个能行：
全局坐标比对会被符号比例差异和文字/标题/GND 符号污染，正负样本区分不开（实测）。
但"某个引脚朝哪个方向出线"是**符号无关**的量：
  · 电阻竖放 → 两脚导线一上一下
  · 电阻横放 → 两脚导线一左一右
朝向认错、位置错乱、漏接，都会直接改变这个集合。

做法：
  1. 图上：给定每个引脚的像素坐标，找**端点落在该点附近**的线段，取离开方向
  2. 工程里：引脚坐标由符号+rotation 算出，找端点重合的导线，取离开方向
  3. 逐引脚比较方向集合
"""
import zipfile

G = 254000
EPS_PX = 2.0        # 图上端点吸附半径（像素）
EPS_G = 0.6         # 工程里端点吸附半径（格）


def _dir(a, b):
    return ((b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1]))


def _image_dirs(image, components, ppg):
    import numpy as np
    from PIL import Image
    from ..recognize import segments as S
    im = Image.open(image).convert("L")
    ink = np.array(im) < 140
    segs = [(s["a"], s["b"]) for s in S.as_segments(S.extract(ink))]

    out = {}
    for c in components:
        for name, (px, py) in c.get("pins", {}).items():
            dirs = set()
            for (x1, y1), (x2, y2) in segs:
                for tip, other in (((x1, y1), (x2, y2)), ((x2, y2), (x1, y1))):
                    if abs(tip[0] - px) <= EPS_PX and abs(tip[1] - py) <= EPS_PX:
                        # 图像 y 向下 → 换到 Proteus 方向（y 取反）
                        dirs.add((_dir((0, 0), (other[0] - tip[0], -(other[1] - tip[1])))))
            out[(c["ref"], name)] = dirs
    return out


def _project_dirs(project, netlist, donor):
    from ..route.plan import pin_table
    from . import file_netlist
    tips = pin_table(netlist, donor)
    buf = file_netlist.reader.load(project)
    segs, i = [], 0
    while True:
        k = buf.find(b"WIRE", i)
        if k < 0:
            break
        i = k + 1
        if buf[k - 1] != 0x7F or buf[k - 2] != 0x02:
            continue
        n = int.from_bytes(buf[k + 4:k + 8], "big")
        if not (2 <= n <= 64):
            continue
        pts, p = [], k + 9
        for _ in range(n):
            pts.append((int.from_bytes(buf[p:p + 4], "little", signed=True) / G,
                        int.from_bytes(buf[p + 4:p + 8], "little", signed=True) / G))
            p += 8
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            segs.append(((x1, y1), (x2, y2)))

    out = {}
    for (ref, name), (tx, ty, dx, dy) in tips.items():
        dirs = set()
        for (x1, y1), (x2, y2) in segs:
            for tip, other in (((x1, y1), (x2, y2)), ((x2, y2), (x1, y1))):
                if abs(tip[0] - tx) <= EPS_G and abs(tip[1] - ty) <= EPS_G:
                    dirs.add(_dir((0, 0), (other[0] - tip[0], other[1] - tip[1])))
        out[(ref, name)] = dirs
    return out


def compare(image, project, netlist, components, donor, ppg):
    img = _image_dirs(image, components, ppg)
    prj = _project_dirs(project, netlist, donor)

    rows, bad = [], []
    for key in sorted(set(img) & set(prj)):
        a, b = img[key], prj[key]
        if not a and not b:
            continue
        same = a == b
        rows.append({"pin": list(key), "image": sorted(a), "project": sorted(b),
                     "match": same})
        if not same:
            bad.append({"pin": list(key), "image": sorted(a), "project": sorted(b)})

    checked = len(rows)
    return {
        "ok": checked > 0 and len(bad) <= max(1, checked // 10),
        "checked_pins": checked,
        "mismatched": len(bad),
        "details": bad[:12],
        "note": "逐引脚比对出线方向。朝向错/位置错乱/漏接会直接改变这个集合 —— "
                "这是能抓到 rotation 错误的检查，netdiff 抓不到。",
    }
