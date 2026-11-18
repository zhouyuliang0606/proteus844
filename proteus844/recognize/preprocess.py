"""图像预处理：把"导线"从"文字和符号"里择出来。

两个毛病一直在拖累下游（初筛、自动定引脚）：
  1. 固定阈值 140 抓不到浅灰线 → 网被误判成断开
  2. 文字笔画和导线粘连 → 两条网被误判成短接

做法：
  · Otsu 自适应阈值（按图自身灰度分布定），再和固定值取较小者，保证不漏浅线
  · 去掉小的连通块（文字的每个字、标点），导线是长条，不会被误删
"""
import numpy as np

try:
    from scipy import ndimage as ndi
except Exception:                                   # 没有 scipy 时退化
    ndi = None


def otsu(gray):
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = np.dot(np.arange(256), hist)
    w_b = np.cumsum(hist)
    sum_b = np.cumsum(hist * np.arange(256))
    w_f = total - w_b
    with np.errstate(divide="ignore", invalid="ignore"):
        m_b = np.where(w_b > 0, sum_b / w_b, 0)
        m_f = np.where(w_f > 0, (sum_all - sum_b) / w_f, 0)
        var = w_b * w_f * (m_b - m_f) ** 2
    var = np.nan_to_num(var)
    return int(np.argmax(var))


def label(mask):
    """四连通标记（不依赖 scipy）"""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    cur = 0
    stack = []
    for y in range(h):
        for x in range(w):
            if mask[y, x] and lab[y, x] == 0:
                cur += 1
                stack.append((y, x))
                lab[y, x] = cur
                while stack:
                    cy, cx = stack.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                            lab[ny, nx] = cur
                            stack.append((ny, nx))
    return lab, cur


def label_fast(mask):
    if ndi is not None:
        lab, n = ndi.label(mask, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
        return lab, n
    return label(mask)


def wire_mask(gray, base=140, max_glyph=11, min_extent=14, use_otsu=True):
    """返回只含长线条的二值掩膜。

    max_glyph   : 长宽都小于这个值、且外接框很小的连通块当作文字丢掉
    min_extent  : 连通块最大边长小于它的一律丢（文字、标点、杂点）
    """
    th = base
    if use_otsu:
        th = max(base, otsu(gray))      # Otsu 通常更高，能抓到浅灰线
    ink = gray < th
    lab, n = label_fast(ink)
    if n == 0:
        return ink, th, 0
    keep = np.zeros(n + 1, dtype=bool)
    ys, xs = np.nonzero(ink)
    order = np.argsort(lab[ys, xs], kind="stable")
    # 逐块统计外接框
    boxes = {}
    for i in range(len(order)):
        v = lab[ys[order[i]], xs[order[i]]]
        b = boxes.get(v)
        y, x = ys[order[i]], xs[order[i]]
        if b is None:
            boxes[v] = [y, y, x, x]
        else:
            if y < b[0]:
                b[0] = y
            if y > b[1]:
                b[1] = y
            if x < b[2]:
                b[2] = x
            if x > b[3]:
                b[3] = x
    dropped = 0
    for v, (y0, y1, x0, x1) in boxes.items():
        h, w = y1 - y0 + 1, x1 - x0 + 1
        long_side = max(h, w)
        if long_side < min_extent or (h <= max_glyph and w <= max_glyph):
            dropped += 1
            continue
        keep[v] = True
    out = keep[lab]
    return out, th, dropped


def stats(gray, base=140, **kw):
    m, th, dropped = wire_mask(gray, base=base, **kw)
    return {"threshold": th, "ink_pixels": int(gray.size),
            "wire_pixels": int(m.sum()), "dropped_blobs": dropped}
