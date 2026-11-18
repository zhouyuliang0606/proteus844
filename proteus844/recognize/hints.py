"""给 AI 看的放大标注图：把一个器件周围放大，把候选端点编号标出来。

目的：让 AI **读数字**而不是**量像素**。
原来的做法是"看截图猜坐标"，这张图把候选点都编好号并给出坐标表，
AI 只要说"引脚 A 是 3 号"，或者直接引用表里的坐标。

输出：
  · PNG：放大后的裁剪，候选端点画圈 + 标号
  · JSON：{序号: (x, y)}，坐标是**原图**坐标
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw


def _endpoints(segs, box, pad=18):
    x0, y0, x1, y1 = box
    raw = []
    for g in segs:
        for p in (g["a"], g["b"]):
            if x0 - pad <= p[0] <= x1 + pad and y0 - pad <= p[1] <= y1 + pad:
                q = (float(p[0]), float(p[1]))
                if not any(abs(q[0] - r[0]) <= 0.6 and abs(q[1] - r[1]) <= 0.6 for r in raw):
                    raw.append(q)
    return sorted(raw, key=lambda q: (q[1], q[0]))


def annotate(image_path, segs, bbox, out_png, scale=8, pad=18, max_points=80):
    im = Image.open(image_path).convert("RGB")
    x0, y0, x1, y1 = bbox
    box = (max(0, int(x0 - pad)), max(0, int(y0 - pad)),
           min(im.width, int(x1 + pad)), min(im.height, int(y1 + pad)))
    crop = im.crop(box).resize(((box[2] - box[0]) * scale, (box[3] - box[1]) * scale),
                               Image.NEAREST)
    d = ImageDraw.Draw(crop)

    # 器件框
    d.rectangle([(x0 - box[0]) * scale, (y0 - box[1]) * scale,
                 (x1 - box[0]) * scale, (y1 - box[1]) * scale],
                outline=(0, 128, 255), width=2)

    pts = _endpoints(segs, bbox, pad)[:max_points]
    table = {}
    for i, (px, py) in enumerate(pts, 1):
        cx = (px - box[0]) * scale
        cy = (py - box[1]) * scale
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], outline=(255, 0, 0), width=2)
        d.text((cx + 11, cy - 6), str(i), fill=(200, 0, 0))
        table[i] = (px, py)

    crop.save(out_png)
    return {"png": out_png, "crop_box": box, "scale": scale,
            "points": table, "count": len(table),
            "note": "坐标是原图像素；器件框是蓝框；红圈是本器件附近的导线端点"}


def as_text(result, per_line=6):
    """把坐标表排成便于阅读的文字"""
    items = list(result["points"].items())
    lines = [f"# 放大图 {result['png']}  （缩放 {result['scale']}×，框 {result['crop_box']}）"]
    for i in range(0, len(items), per_line):
        chunk = items[i:i + per_line]
        lines.append("  " + "   ".join(f"{k:>2}:({v[0]:.1f},{v[1]:.1f})" for k, v in chunk))
    return "\n".join(lines)
