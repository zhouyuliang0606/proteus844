"""按"教科书套路"直接生成几何，不走通用走廊搜索。

通用布线器对每条网独立找路径，出来的线各自绕行 —— 电气对，但读不懂。
真实原理图的套路是固定的：

    源列          通道带            门列          汇列        输出链
    LS3 ──┐
          │(c_C)────────────────→ U3:A.2
          └────────────────────→ U3:B.4

规则：
  1. 每个源网在通道带里占一根专属竖干，主干之间至少隔 2 格
  2. 竖干只在自己那一列上下，不跑到别人的列
  3. 进引脚的横向段永远笔直（同一行）
  4. 多脚网用 star：所有分支都终止在 (通道x, 驱动行)
  5. 出线/进线都必须顺着引脚朝向，先沿朝向走 2 格再拐
"""
import collections

COL_GAP = 22.0       # 列间距（格）
ROW_GAP = 8.0        # 行间距（格）
LEAD = 2.0           # 沿引脚朝向先走几格


def _pins(donor, device):
    from .plan import _symbol_pins
    return _symbol_pins(donor, device)


def _rot(dx, dy, ddx, ddy, ang):
    a = int(ang) % 360
    if a == 0:
        return dx, dy, ddx, ddy
    if a == 90:
        return -dy, dx, -ddy, ddx
    if a == 180:
        return -dx, -dy, -ddx, -ddy
    return dy, -dx, ddy, -ddx


def _is_out(ddx, ddy):
    return ddx > 0 or ddy > 0


def analyse(netlist, donor):
    """复用 place 的图（已含两脚器件的上下游兜底）"""
    from . import place as PL
    refs, info, edges, _ = PL.build_graph(netlist, donor)
    level, _ = PL.levels_of(refs, edges)
    return info, level, edges


def layout(netlist, donor, col_gap=COL_GAP, row_gap=ROW_GAP, x0=10.0):
    comps = netlist["components"]
    info, level, edges = analyse(netlist, donor)
    by_level = collections.defaultdict(list)
    for c in comps:
        by_level[level[c["ref"]]].append(c["ref"])
    placed = {}
    for lv in sorted(by_level):
        refs = sorted(by_level[lv])
        n = len(refs)
        for i, r in enumerate(refs):
            placed[r] = (x0 + lv * col_gap, (n - 1) * row_gap / 2 - i * row_gap)
    # Proteus 的图纸以页框中心为原点 —— 必须把电路居中，
    # 否则整块会贴到图纸右边（踩过这个坑）。
    if placed:
        cx = (max(v[0] for v in placed.values()) + min(v[0] for v in placed.values())) / 2
        cy = (max(v[1] for v in placed.values()) + min(v[1] for v in placed.values())) / 2
        placed = {k: (v[0] - cx, v[1] - cy) for k, v in placed.items()}
    out = []
    for c in comps:
        d = dict(c)
        d["x"], d["y"] = placed[c["ref"]]
        d.setdefault("rotation", 0)
        out.append(d)
    return {"components": out, "nets": netlist.get("nets", []),
            "terminals": netlist.get("terminals", []),
            "_info": info, "_level": level}


def _rg(v):
    return float(round(v, 1))


def routes(layout_nl, donor, lead=LEAD, chan_step=3.0, min_gap=2.0):
    info = layout_nl["_info"]
    comps = {c["ref"]: c for c in layout_nl["components"]}

    def pin_xy(ref, name):
        o = info[ref][name]
        return (comps[ref]["x"] + o[0], comps[ref]["y"] + o[1]), (o[2], o[3])

    used, plan_nets = [], []
    for idx, net in enumerate(layout_nl["nets"]):
        pins = [tuple(p) for p in net["pins"]]
        driver, targets = None, []
        for ref, name in pins:
            (_, _), (ddx, ddy) = pin_xy(ref, name)
            if _is_out(ddx, ddy) and driver is None:
                driver = (ref, name)
            else:
                targets.append((ref, name))
        if driver is None:
            driver, targets = pins[0], pins[1:]

        (dx, dy), (ddx, ddy) = pin_xy(*driver)
        sx, sy = dx + ddx * lead, dy + ddy * lead          # 先顺着出线方向走
        # 通道 x：在"离开点"右侧，且不能落到目标左边
        cx = sx + max(min_gap, 2.0) + (idx % 3) * chan_step
        for ref, name in targets:
            (tx, _), _ = pin_xy(ref, name)
            cx = min(cx, tx - min_gap)
        while any(abs(cx - u) < min_gap for u in used):
            cx -= 0.5
        used.append(cx)

        def _clean(pts):
            out = [pts[0]]
            for p in pts[1:]:
                if p != out[-1]:
                    out.append(p)
            return out

        jx, jy = _rg(cx), _rg(sy)
        driver_br = _clean([[_rg(dx), _rg(dy)], [_rg(sx), _rg(sy)], [jx, jy]])
        target_brs = []
        for ref, name in targets:
            (tx, ty), (tdx, tdy) = pin_xy(ref, name)
            ax, ay = _rg(tx + tdx * lead), _rg(ty + tdy * lead)
            target_brs.append({"pin": [ref, name],
                               "points": _clean([[_rg(tx), _rg(ty)], [ax, ay],
                                                 [_rg(cx), ay], [jx, jy]])})

        if len(pins) > 2:
            # 星形要求分支互不重叠，而一根竖干多个抽头必然重叠
            # → 改成「驱动对每个目标各一条路径」，重叠部分画面上就是一根线
            # 星形：驱动端一条 + 每个目标一条，全部终止在 J=(cx, 驱动行)。
            # vendor 已放开"分支可重叠"，共用同一段竖干合法 ——
            # 画面上就是一根竖干挂多个抽头，正是教科书的样子。
            branches = [{"pin": list(driver), "points": driver_br}] + target_brs
            plan_nets.append({"name": net.get("name"), "junction": [jx, jy],
                              "branches": branches, "path": None})
        else:
            tgt = target_brs[0]["points"] if target_brs else []
            path = _clean(driver_br + list(reversed(tgt[:-1])))
            plan_nets.append({"name": net.get("name"), "junction": None,
                              "branches": None, "path": path})
    return {"schema_version": "1.0", "components": layout_nl["components"],
            "nets": plan_nets, "warnings": []}
