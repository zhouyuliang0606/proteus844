"""结点识别：用距离变换（EDT）的峰值区分「实心结点」和「线交叉」。

原理：线宽 1~2px 时 EDT 峰值 ≈1.0~1.5；实心结点直径 4~5px，峰值 ≈2.2。
      门输出的小圆圈是**环**，它的峰值出现在环上、且中心是空的 —— 用"中心是否空"排除。
"""
import numpy as np
from scipy.ndimage import distance_transform_edt, label, maximum_filter


def detect(ink, dot_peak=2.0, cluster=3.0, exclude_rings=True):
    """返回 [{"x":..., "y":..., "peak":...}]，坐标为原图像素。"""
    edt = distance_transform_edt(ink)
    peak = maximum_filter(edt, size=5)
    mask = (edt >= dot_peak) & (edt == peak)
    lab, n = label(mask)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) == 0:
            continue
        y, x = float(ys.mean()), float(xs.mean())
        val = float(edt[ys, xs].max())
        if exclude_rings and _is_ring(ink, int(round(y)), int(round(x)), val):
            continue
        out.append({"x": x, "y": y, "peak": val})
    # 邻近合并
    out.sort(key=lambda d: -d["peak"])
    merged = []
    for d in out:
        if not any(abs(d["x"] - m["x"]) < cluster and abs(d["y"] - m["y"]) < cluster
                   for m in merged):
            merged.append(d)
    merged.sort(key=lambda d: (d["y"], d["x"]))
    return merged


def _is_ring(ink, y, x, radius, pad=3):
    """结点中心是否为空洞：实心点中心是墨，圆环中心是白。"""
    r = int(round(radius)) + pad
    y0, y1 = max(0, y - r), min(ink.shape[0], y + r + 1)
    x0, x1 = max(0, x - r), min(ink.shape[1], x + r + 1)
    patch = ink[y0:y1, x0:x1]
    if patch.size == 0:
        return False
    cy, cx = y - y0, x - x0
    if not (0 <= cy < patch.shape[0] and 0 <= cx < patch.shape[1]):
        return False
    return not bool(patch[cy, cx])
