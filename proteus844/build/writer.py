"""按 RoutePlan 写 .pdsprj：两脚网用 connect(points=)，多脚网用 set_star。"""
import os
import sys

G = 254000


def _vendor():
    v = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "vendor", "ref844")
    if v not in sys.path:
        sys.path.insert(0, v)
    return v


def build(netlist, plan_doc, donor, out):
    _vendor()
    from component_codec import Circuit

    c = Circuit(donor)
    # 布线器可能挪过器件：以计划里的坐标为最终准
    if isinstance(plan_doc, dict) and plan_doc.get("components"):
        by_ref = {x["ref"]: x for x in plan_doc["components"]}
        netlist = dict(netlist)
        netlist["components"] = [
            dict(comp, **{k: by_ref[comp["ref"]][k]
                          for k in ("x", "y", "rotation") if k in by_ref[comp["ref"]]})
            if comp["ref"] in by_ref else comp
            for comp in netlist["components"]]
    # ★ donor 往往不是空工程（本身就是一张画好的图）：先把它的器件和导线全清掉，
    #   否则新图会叠加在旧图上 —— 这正是"画面里有一堆斜线"的真凶。
    cleared = {"parts": len(c._parts), "connections": len(c._connections),
               "terminals": len(c._terminals)}
    c._parts = []
    c._connections = []
    c._terminals = []
    for comp in netlist["components"]:
        c.add(device=comp["device"], ref=comp["ref"],
              value=str(comp.get("value") or comp["device"]),
              x=int(round(comp["x"] * G)), y=int(round(comp["y"] * G)),
              rotation=int(comp.get("rotation", 0)))

    routes = {n["name"]: n for n in (plan_doc or {}).get("nets", [])}
    # ★ Proteus 要求导线从"器件列表里更靠前"的那一端开始记录，否则几何会被画歪
    #   （实测：同一条路径对调首尾，斜线能量 0.64 -> 0.0009）
    order = {c["ref"]: i for i, c in enumerate(netlist["components"])}

    def ordered(pins, path):
        """把 pins/path 统一成「先器件在前」的方向"""
        if len(pins) != 2 or not path:
            return pins, path
        if order.get(pins[0][0], 0) <= order.get(pins[1][0], 0):
            return pins, path
        return [pins[1], pins[0]], list(reversed(path))

    # 分两种：两脚网直接带折线连；多脚网先建拓扑再 set_star
    for net in netlist.get("nets", []):
        pins = [tuple(p) for p in net["pins"]]
        r = routes.get(net.get("name", "?"))
        if len(pins) == 2:
            if r and r.get("path"):
                pp, ppath = ordered(pins, r["path"])
                pts = [(int(round(x * G)), int(round(y * G))) for x, y in ppath]
                c.connect(pp[0], pp[1], points=pts)
            else:
                pp, _ = ordered(pins, None)
                c.connect(pp[0], pp[1])
        else:
            if not (r and r.get("paths")):
                for a, b in zip(pins, pins[1:]):
                    c.connect(a, b)

    # 多脚网：显式路径（每对引脚一条），重叠的竖干在画面上就是一根线
    for net in netlist.get("nets", []):
        pins = [tuple(p) for p in net["pins"]]
        r = routes.get(net.get("name", "?"))
        if not r or not r.get("paths"):
            continue
        for item in r["paths"]:
            a, b = tuple(item["pair"][0]), tuple(item["pair"][1])
            pts = [(int(round(x * G)), int(round(y * G))) for x, y in item["points"]]
            c.connect(a, b, points=pts)

    # 多脚网：星形显式几何
    for net in netlist.get("nets", []):
        pins = [tuple(p) for p in net["pins"]]
        r = routes.get(net.get("name", "?"))
        if not r or len(pins) < 3 or not r.get("junction"):
            continue
        branches = [(tuple(b["pin"]),
                     [(int(round(x * G)), int(round(y * G))) for x, y in b["points"]])
                    for b in r["branches"]]
        c.set_star(branches)

    terminal_errors = []
    for t in netlist.get("terminals", []):
        try:
            c.add_terminal(t["kind"], t["name"], pin=tuple(t["pin"]))
        except Exception as exc:                   # 不静默：收集起来返回
            terminal_errors.append({"terminal": t, "error": f"{type(exc).__name__}: {exc}"})

    c.save(out, overwrite=True)
    return {"path": out, "terminal_errors": terminal_errors,
            "cleared_from_donor": cleared}
