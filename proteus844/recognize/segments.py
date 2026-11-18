"""线段抽取：把二值图里的横线、竖线各抽成一组线段。

做法：逐行找连续墨迹 run → 相邻行的 run 若 x 区间重叠则合并（并查集）→
      每个连通块就是一条横线；竖线同理按列做。
只保留「细长」的块（厚度 ≤ 4px 且长度 ≥ min_len），文字笔画会被厚度/长度滤掉。
"""
from collections import defaultdict


def _runs(bits, min_len):
    """一维布尔数组 → [(start, end)] 连续 True 段（闭区间）"""
    out, start = [], None
    for i, v in enumerate(bits):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    if start is not None and len(bits) - start >= min_len:
        out.append((start, len(bits) - 1))
    return out


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _extract(ink, axis, min_len, max_thick=4):
    """axis=0 横线（逐行）；axis=1 竖线（逐列）"""
    n = ink.shape[0] if axis == 0 else ink.shape[1]
    runs = []                                  # (line_no, lo, hi)
    for k in range(n):
        line = ink[k, :] if axis == 0 else ink[:, k]
        for lo, hi in _runs(line.tolist(), min_len):
            runs.append((k, lo, hi))
    if not runs:
        return []

    index = defaultdict(list)                  # 把 run 按 line_no 索引
    for i, (k, lo, hi) in enumerate(runs):
        index[k].append(i)

    uf = _UF()
    for k in sorted(index):
        for i in index[k]:
            for j in index.get(k - 1, ()):      # 只跟上一行比，避免重复
                _, lo_i, hi_i = runs[i]
                _, lo_j, hi_j = runs[j]
                if lo_i <= hi_j and lo_j <= hi_i:   # x 区间重叠
                    uf.union(i, j)

    groups = defaultdict(list)
    for i in range(len(runs)):
        groups[uf.find(i)].append(runs[i])

    out = []
    for members in groups.values():
        lines = [m[0] for m in members]
        lo = min(m[1] for m in members)
        hi = max(m[2] for m in members)
        thick = max(lines) - min(lines) + 1
        if thick > max_thick:
            continue                            # 太厚 = 文字/填充块
        pos = sum(lines) / len(lines)
        out.append({"axis": axis, "pos": pos, "lo": lo, "hi": hi,
                    "thick": thick, "length": hi - lo + 1})
    return out


def extract(ink, min_len=12, max_thick=4):
    """返回 {'horizontal': [...], 'vertical': [...]}，坐标为原图像素。

    每项: {"pos": 固定坐标, "lo"/"hi": 跨度, "length", "thick"}
    转成端点: 横线 ((lo,pos),(hi,pos))，竖线 ((pos,lo),(pos,hi))
    """
    h = _extract(ink, 0, min_len, max_thick)
    v = _extract(ink, 1, min_len, max_thick)
    return {"horizontal": h, "vertical": v}


def endpoints(seg):
    """线段 → 两个端点 (x,y)"""
    if seg["axis"] == 0:
        return (seg["lo"], seg["pos"]), (seg["hi"], seg["pos"])
    return (seg["pos"], seg["lo"]), (seg["pos"], seg["hi"])


def as_segments(raw):
    """统一成 [{"a": (x,y), "b": (x,y), "axis": 0/1}]"""
    out = []
    for kind in ("horizontal", "vertical"):
        for seg in raw[kind]:
            a, b = endpoints(seg)
            out.append({"a": a, "b": b, "axis": seg["axis"]})
    return out
