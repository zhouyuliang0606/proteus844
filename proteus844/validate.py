"""网表校验：把错误拖到最前面，别等 Proteus 打开才发现。

返回 {"ok": bool, "code":..., "errors":[...], "detail": {...}}
"""
import re

# vendor 要求位号里必须含数字（LS_A 会被拒），这里对齐，别等写到一半才报
REF_RE = re.compile(r"^[A-Z][A-Z0-9_]*\d[A-Z0-9_]*(?::[A-Z])?$")


def validate(netlist, donor):
    from . import errors as E
    from .route import plan as P

    errs = []
    comps = netlist.get("components") or []
    if not comps:
        return E.fail(E.Code.NETLIST_INVALID, "components 为空")

    refs = [c.get("ref") for c in comps]
    dup = {r for r in refs if refs.count(r) > 1}
    if dup:
        errs.append({"code": E.Code.NETLIST_INVALID, "message": f"位号重复: {sorted(dup)}"})

    # 只给拓扑（没 x/y）时不做引脚级校验 —— 坐标还没算，校验会 KeyError('x')，
    # 而被误报成 DONOR_MISSING_DEVICE，误导性极强。
    # 星形结点只支持 2~4 根线 → 一条网最多 4 个引脚。
    # 超了 vendor 会抛 "Each native junction needs two to four wires"，很难懂。
    from .pipeline import SUPPLY_KIND
    for n in netlist.get("nets") or []:
        pins = n.get("pins") or []
        if (n.get("name") or "").upper() in SUPPLY_KIND:
            continue                   # 电源网后面会拆成端子，不受四脚限制
        if len(pins) > 4:
            errs.append({"code": E.Code.NETLIST_INVALID,
                         "message": f"网 {n.get('name')} 有 {len(pins)} 个引脚，"
                                    f"星形结点最多 4 个；请拆成两级（加缓冲门）"})

    topology_only = any("x" not in c or "y" not in c for c in comps)
    # 位号规则在拓扑阶段就要查：vendor 写文件时才拒（要求含数字），
    # 等画完再报就白干了。
    bad_refs = [c.get("ref") for c in comps if not REF_RE.match(c.get("ref", ""))]
    if bad_refs:
        errs.append({"code": E.Code.REF_INVALID,
                     "message": f"位号不合规: {bad_refs}"
                                f"（必须字母开头且含数字，如 LS1 / U1:D / R14）"})
    if topology_only:
        missing = [c.get("ref") for c in comps if "device" not in c]
        if missing:
            return E.fail(E.Code.NETLIST_INVALID, f"这些器件没有 device: {missing}")
        # 只检查型号在 donor 里存不存在
        for c in comps:
            try:
                P._symbol_pins(donor, c["device"])
            except Exception:
                return E.fail(E.Code.DONOR_MISSING_DEVICE,
                              f"donor 里没有 {c['device']}（{c.get('ref')}）")
        if errs:                      # 拓扑阶段已经能判出来的问题不能吞掉
            return E.fail(E.Code.NETLIST_INVALID, f"{len(errs)} 处问题", errors=errs)
        return E.ok(topology=True, components=len(comps),
                    nets=len(netlist.get("nets") or []),
                    note="只给了拓扑，坐标由自动布局生成；引脚级校验在布局之后做")

    # 位号规则在**拓扑阶段**就要查：vendor 写文件时会拒（要求含数字），
    # 等画完再报就白干了。
    bad_refs = [c.get("ref") for c in comps if not REF_RE.match(c.get("ref", ""))]
    if bad_refs:
        return E.fail(E.Code.REF_INVALID,
                      f"位号不合规: {bad_refs}（必须字母开头且含数字，如 LS1 / U1:D / R14）")

    try:
        tips = P.pin_table(netlist, donor)
        known_devs = set(P._symbol_pins(donor, c["device"]) and c["device"] for c in comps)
    except E.Code.__class__ if False else Exception as exc:    # donor 里没有该型号
        return E.fail(E.Code.DONOR_MISSING_DEVICE, str(exc))

    for c in comps:
        if not REF_RE.match(c.get("ref", "")):
            errs.append({"code": E.Code.REF_INVALID,
                         "message": f"位号不合规: {c.get('ref')!r}"})
        for k in ("device", "x", "y"):
            if k not in c:
                errs.append({"code": E.Code.NETLIST_INVALID,
                             "message": f"{c.get('ref')} 缺字段 {k}"})
        if c.get("device") not in known_devs:
            errs.append({"code": E.Code.DONOR_MISSING_DEVICE,
                         "message": f"donor 里没有 {c.get('device')}"})

    seen_pin = {}
    for net in netlist.get("nets") or []:
        pins = [tuple(p) for p in net.get("pins", [])]
        if len(pins) < 2:
            errs.append({"code": E.Code.NETLIST_INVALID,
                         "message": f"网 {net.get('name')} 少于两个引脚"})
        for p in pins:
            if p not in tips:
                errs.append({"code": E.Code.PIN_NOT_IN_SYMBOL,
                             "message": f"网 {net.get('name')} 的引脚 {p} 在符号里不存在"})
            if p in seen_pin:
                errs.append({"code": E.Code.NETLIST_INVALID,
                             "message": f"引脚 {p} 同时属于 {seen_pin[p]} 和 {net.get('name')}"})
            seen_pin[p] = net.get("name")

    for t in netlist.get("terminals") or []:
        if t.get("kind") not in ("ground", "power", "input", "output", "bidir", "label"):
            errs.append({"code": E.Code.NETLIST_INVALID,
                         "message": f"终端 kind 必须小写且合法: {t.get('kind')!r}"})

    if errs:
        return E.fail(E.Code.NETLIST_INVALID, f"{len(errs)} 处问题", errors=errs)
    return E.ok(components=len(comps), nets=len(netlist.get("nets") or []),
                pins=len(seen_pin))
