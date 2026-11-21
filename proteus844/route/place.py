"""自动布局：给「器件 + 网表」，工具自己决定器件摆哪。

AI 只需要说清**拓扑**（谁连谁），坐标由这里算出来 —— 这才是 CAD 式的分工。

做法（简化的分层布局）：
  1. 从网表建器件图：输出脚 → 输入脚 的边
  2. 最长路径分层：源器件在最左，汇在最右
  3. 层内按邻居重心排序（3 轮），减少交叉
  4. 给坐标：列间距 = 最大符号宽 + 间隔；行间距 = 最大符号高 + 间隔

产物是带坐标的网表，可直接交给 plan_route。
"""
import collections

MARGIN_X = 10          # 左边距
GAP_X = 8              # 列间距（格）
GAP_Y = 6              # 行间距（格）


def _pins(donor, device):
    from .plan import _symbol_pins
    return _symbol_pins(donor, device)


def _is_output(pin_info):
    dx, dy, ddx, ddy = pin_info
    return ddx > 0 or ddy > 0


def _flow_rank(pin_info):
    """判上下游的兜底分：**分高 = 更靠下游**。

    依据引脚朝向：
      · 朝右 (ddx>0) → 这是输出脚，器件在上游 → 0 分
      · 朝上/下（竖放器件） → 2 分，当作下游
      · 朝左 (ddx<0) → 这是输入脚，器件在下游 → 3 分
    典型用途：R14.2（朝右）→ D2.A（朝上）应当 R14 在上游，
    而 `_is_output` 把两者都判成"输出"，建不出边。
    """
    dx, dy, ddx, ddy = pin_info
    if ddx > 0:
        return 0
    if ddx < 0:
        return 3
    return 2


def build_graph(netlist, donor):
    """器件级有向图 + 每个器件的脚方向表"""
    comps = netlist["components"]
    refs = [c["ref"] for c in comps]
    info = {c["ref"]: _pins(donor, c["device"]) for c in comps}
    edges = collections.defaultdict(set)
    degree_in = {r: 0 for r in refs}
    for net in netlist.get("nets", []):
        pins = [tuple(p) for p in net["pins"]]
        for i in range(len(pins)):
            for j in range(i + 1, len(pins)):
                (ra, pa), (rb, pb) = pins[i], pins[j]
                if ra == rb:
                    continue
                ia, ib = info[ra].get(pa), info[rb].get(pb)
                if ia and ib:
                    if _is_output(ia) and not _is_output(ib):
                        edges[ra].add(rb)
                    elif _is_output(ib) and not _is_output(ia):
                        edges[rb].add(ra)
                    elif len(info[ra]) <= 2 and len(info[rb]) <= 2:
                        # 两个都是两脚器件（如 R→LED）且方向判不出来：
                        # 用「引脚朝向」定上下游（分低的是上游）。
                        # 只对两脚器件这么做 —— 逻辑门之间这么做会互指成环。
                        ka, kb = _flow_rank(ia), _flow_rank(ib)
                        if ka < kb:
                            edges[ra].add(rb)
                        elif kb < ka:
                            edges[rb].add(ra)
                edge_key = (min(ra, rb), max(ra, rb))
                edges.setdefault(("undirected",) + edge_key, set())
    return refs, info, {k: v for k, v in edges.items() if isinstance(k, str)}, degree_in


def levels_of(refs, edges):
    """最长路径分层；环用迭代松弛兜底"""
    preds = collections.defaultdict(set)
    for a, outs in edges.items():
        for b in outs:
            preds[b].add(a)
    level = {r: 0 for r in refs}
    for _ in range(len(refs) + 2):
        changed = False
        for a, outs in edges.items():
            for b in outs:
                if level[b] < level[a] + 1:
                    level[b] = level[a] + 1
                    changed = True
        if not changed:
            break
    return level, preds


def _order_layer(layer, preds, succ, pos, rounds=3):
    for _ in range(rounds):
        layer.sort(key=lambda r: (sum(pos.get(p, 0) for p in preds.get(r, ())) /
                                  max(1, len(preds.get(r, ()))), r))
        for i, r in enumerate(layer):
            pos[r] = i
    return layer


def place(netlist, donor, gap_x=GAP_X, gap_y=GAP_Y, margin=MARGIN_X, sheet=None,
          max_per_col=None):
    """自动布局。

    sheet=(宽, 高) 时，会自动收缩间距让整块装进纸里（能装下才缩）。
    max_per_col 给定时，一列超过这么多个就折到右边新开一列 ——
    20+ 器件的电路不折列会拉成一条 200 多格高的面条。
    """
    """返回带坐标的新网表（不改原对象）"""
    refs, info, edges, _ = build_graph(netlist, donor)
    level, preds = levels_of(refs, edges)
    succ = collections.defaultdict(set)
    for a, outs in edges.items():
        for b in outs:
            succ[a].add(b)

    max_w = max((max(abs(v[0]) for v in info[r].values()) for r in refs), default=5) * 2 + 2
    max_h = max((max(abs(v[1]) for v in info[r].values()) for r in refs), default=3) * 2 + 2

    by_level = collections.defaultdict(list)
    for r in refs:
        by_level[level[r]].append(r)
    pos = {}
    for lv in sorted(by_level):
        by_level[lv] = _order_layer(by_level[lv], preds, succ, pos)

    # 想装进纸里就先收缩间距（只在真的能装下时才缩，缩到 3 格为止）
    if sheet:
        ncol = len(by_level)
        nrow = max((len(v) for v in by_level.values()), default=1)
        usable_w = sheet[0] - 2 * margin
        usable_h = sheet[1] - 2 * margin
        if ncol > 1:
            gap_x = max(3, min(gap_x, (usable_w - ncol * max_w) // (ncol - 1)))
        if nrow > 1:
            gap_y = max(3, min(gap_y, (usable_h - nrow * max_h) // (nrow - 1)))

    out = {c["ref"]: dict(c) for c in netlist["components"]}
    # 折列：把一列超过 max_per_col 的部分挪到右边的顺位新列
    columns = []          # [(refs...), ...] 从左到右
    for lv in sorted(by_level):
        layer = by_level[lv]
        if max_per_col and len(layer) > max_per_col:
            for i in range(0, len(layer), max_per_col):
                columns.append(layer[i:i + max_per_col])
        else:
            columns.append(layer)

    # 每列按**自己那一列**的器件尺寸算宽度/行距。
    # 用全局最大值会让一个高器件（数码管）把每一行都撑开，
    # 22 器件的编码器因此拉成 212 格高。
    cursor = margin
    for ci, layer in enumerate(columns):
        col_w = max((max(abs(v[0]) for v in info[r].values()) for r in layer), default=5) * 2 + 2
        col_h = max((max(abs(v[1]) for v in info[r].values()) for r in layer), default=3) * 2 + 2
        pitch = col_h + gap_y
        n = len(layer)
        span = max(0, n - 1) * pitch
        for i, ref in enumerate(layer):
            out[ref]["x"] = int(round(cursor))
            out[ref]["y"] = int(round(-((span / 2) - i * pitch)))
            out[ref].setdefault("rotation", 0)
        cursor += col_w + gap_x

    # Proteus 的图纸以页框中心为原点 —— 必须把整体居中，
    # 否则整块会贴到图纸右边（子代实测踩到：7410 骑在右边框上、LED 在图框外）。
    xs = [c["x"] for c in out.values()]
    ys = [c["y"] for c in out.values()]
    if xs:
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
        for c in out.values():
            c["x"] = int(round(c["x"] - cx))
            c["y"] = int(round(c["y"] - cy))
    return {"components": [out[c["ref"]] for c in netlist["components"]],
            "nets": netlist.get("nets", []),
            "terminals": netlist.get("terminals", []),
            "levels": {r: level[r] for r in refs}}
