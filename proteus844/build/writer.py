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


def _check_geometry(netlist, plan_doc):
    """写之前先验证：坐标必须**整格**，导线端点必须落在**引脚或端子上**。

    这条是给"图看着像接上了、其实差半格"兜底的 —— 半格偏差在 Proteus 里
    就是一根线悬在引脚旁边 0.5 格，人一眼就看出没接上。
    宁可报错，也不要悄悄画出一张错的图。
    """
    problems = []
    for comp in netlist["components"]:
        for axis in ("x", "y"):
            v = comp.get(axis)
            if v is None:
                continue
            if abs(v - round(v)) > 1e-6:
                problems.append(f"器件 {comp['ref']} 的 {axis}={v} 不在整格上")

    # 合法端点 = 引脚尖端 + 端子接点
    legal = set()
    for comp in netlist["components"]:
        pin_at = comp.get("pins") or {}
        for _, xy in pin_at.items():
            legal.add((round(comp["x"] + xy[0], 3), round(comp["y"] + xy[1], 3)))
    for t in netlist.get("terminals") or []:
        pos = t.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            legal.add((round(pos[0], 3), round(pos[1], 3)))

    if legal:                                  # 没有引脚表就跳过这条（无法判定）
        for n in (plan_doc or {}).get("nets", []):
            pts = []
            if n.get("path"):
                pts += [n["path"][0], n["path"][-1]]
            for b in n.get("branches") or []:
                bpts = b.get("points") or []
                if bpts:
                    pts += [bpts[0], bpts[-1]]
            for p in pts:
                key = (round(p[0], 3), round(p[1], 3))
                if key not in legal:
                    problems.append(f"网 {n.get('name')} 的端点 {key} 不在任何引脚/端子上")
    if problems:
        raise ValueError("几何校验不通过：\n  " + "\n  ".join(problems[:12]))


def build(netlist, plan_doc, donor, out):
    _vendor()
    from component_codec import Circuit

    _check_geometry(netlist, plan_doc)

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

    # 位号/数值文字偏移：R14 竖放时"100"会压在电阻身上，用 label_offsets 挪开。
    # 单位是格，写进 vendor 的 update。
    for comp in netlist["components"]:
        off = comp.get("label_offsets")
        if not off:
            continue
        try:
            c.update(comp["ref"], label_offsets={
                k: (int(round(v[0] * G)), int(round(v[1] * G)))
                for k, v in off.items() if isinstance(v, (list, tuple)) and len(v) >= 2})
        except Exception as exc:                   # noqa: BLE001
            terminal_errors.append({"label_offsets": comp.get("ref"), "error": str(exc)})

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

    # 电源/地端子：**保持最朴素的写法** —— add_terminal(kind, name, pin=...)，
    # 位置交给 vendor 自己算（引脚外 2 格），它会自动补一根连线。
    # 试过两个"改进"，都会让端子脱离电源网（引擎编译后那根脚变成孤立单脚网）：
    #   · position=引脚坐标（符号压在引脚上）→ 不连
    #   · 自己追加 connection 到 @TERMINAL_xx        → 也不连
    # 实测：朴素写法下 GND 是 6 脚（含 D2.K），改进后只有 5 脚。
    terminal_errors = []
    for t in netlist.get("terminals", []):
        try:
            c.add_terminal(t["kind"], t["name"], pin=tuple(t["pin"]))
        except Exception as exc:                   # noqa: BLE001
            terminal_errors.append({"terminal": t,
                                    "error": f"{type(exc).__name__}: {exc}"})

    # 连线标号（A/B/C/F）：**不可用，且会损坏文件**。
    # 试过按 Proteus 真实记录手工拼字节（见 build/wirelabel.py）：
    # 写出的工程能存盘，但 Proteus 打开后不认（画面空白、网络表编译失败）。
    # 结论：这条记录还差关键字段没解析出来。**默认禁用**，传 labels 只报警告。
    if (plan_doc or {}).get("labels"):
        terminal_errors.append({"label": "unsupported",
                                "error": "连线标号会让工程损坏，已禁用（见 SKILL §3.8）"})

    c.save(out, overwrite=True)
    return {"path": out, "terminal_errors": terminal_errors,
            "cleared_from_donor": cleared}
