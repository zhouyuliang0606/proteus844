"""自动找器件框：从墨迹里减掉导线，剩下的聚成器件。

步骤：
  1. 取二值墨迹
  2. 抽出长的横/竖直线段（导线 + 引脚）→ 从墨迹里减掉
  3. 剩下的连通块 = 器件笔画（弧、圆、数字、字符）
  4. 按尺寸滤掉文字（字高很小）
  5. 邻近的块合并成一个器件（符号由多笔组成）

输出是按面积排序的候选框，交给 AI 打型号。
"""
import numpy as np

try:
    from scipy import ndimage as ndi
except Exception:
    ndi = None


def _runs(mask, min_len):
    """找出长度 ≥ min_len 的纯横/纯竖条，返回它们的掩膜"""
    out = np.zeros_like(mask)
    h, w = mask.shape
    # 横
    for y in range(h):
        row = mask[y]
        x = 0
        while x < w:
            if row[x]:
                s = x
                while x < w and row[x]:
                    x += 1
                if x - s >= min_len:
                    out[y, s:x] = True
            else:
                x += 1
    # 竖
    for x in range(w):
        col = mask[:, x]
        y = 0
        while y < h:
            if col[y]:
                s = y
                while y < h and col[y]:
                    y += 1
                if y - s >= min_len:
                    out[s:y, x] = True
            else:
                y += 1
    return out


def _label(mask):
    if ndi is not None:
        lab, n = ndi.label(mask, structure=np.ones((3, 3), dtype=int))
        return lab, n
    # 退化：逐像素洪水（慢，仅小图）
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    cur = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and lab[y, x] == 0:
                cur += 1
                st = [(y, x)]
                lab[y, x] = cur
                while st:
                    cy, cx = st.pop()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                                lab[ny, nx] = cur
                                st.append((ny, nx))
    return lab, cur


def detect_boxes(gray, threshold=192, min_line=14, min_area=90,
                 max_glyph=12, merge_gap=4, max_boxes=60):
    ink = gray < threshold
    wires = _runs(ink, min_line)
    body = ink & ~wires

    if ndi is not None and merge_gap > 0:
        body_m = ndi.binary_dilation(body, iterations=merge_gap)
    else:
        body_m = body
    lab, n = _label(body_m)
    boxes = []
    if n:
        slices = ndi.find_objects(lab) if ndi is not None else None
        for i in range(1, n + 1):
            m = lab == i
            area = int(m.sum())
            if area < min_area:
                continue
            ys, xs = np.nonzero(m)
            y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
            h, w = y1 - y0 + 1, x1 - x0 + 1
            if h <= max_glyph and w <= max_glyph:      # 文字
                continue
            boxes.append({"bbox": [int(x0), int(y0), int(x1), int(y1)],
                          "area": area, "w": int(w), "h": int(h)})
    boxes.sort(key=lambda b: -b["area"])
    return boxes[:max_boxes]


def iou(a, b):
    x0 = max(a[0], b[0]); y0 = max(a[1], b[1])
    x1 = min(a[2], b[2]); y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0
