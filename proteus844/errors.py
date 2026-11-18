"""统一错误码 —— skill 靠它教恢复动作，别让用户看 traceback。"""


class Code:
    DONOR_MISSING_DEVICE = "DONOR_MISSING_DEVICE"
    PIN_NOT_IN_SYMBOL = "PIN_NOT_IN_SYMBOL"
    REF_INVALID = "REF_INVALID"
    NETLIST_INVALID = "NETLIST_INVALID"
    JUNCTION_AMBIGUOUS = "JUNCTION_AMBIGUOUS"
    ROUTE_OVERLAP = "ROUTE_OVERLAP"
    ROUTE_ENDPOINT_OFF = "ROUTE_ENDPOINT_OFF"
    ROUTE_UNROUTABLE = "ROUTE_UNROUTABLE"
    NET_BROKEN = "NET_BROKEN"
    NET_SHORT = "NET_SHORT"
    PROTEUS_REJECTED = "PROTEUS_REJECTED"
    BAD_ARGUMENT = "BAD_ARGUMENT"
    INTERNAL = "INTERNAL"


HINTS = {
    Code.DONOR_MISSING_DEVICE: "供体工程里没有这个型号。在 Proteus 里放一个该器件、存盘，再用它当 donor。",
    Code.PIN_NOT_IN_SYMBOL: "引脚名对不上符号。用 donor_info 查真实引脚名，别用图上印的脚号。",
    Code.REF_INVALID: "位号不合规。用 U1:A 形式；数字开头或带 # 的会被拒。",
    Code.NETLIST_INVALID: "网表结构不对：器件缺字段、网络为空、引脚重复等。",
    Code.JUNCTION_AMBIGUOUS: "结点判不准。回图放大复核，或改用显式 RoutePlan。",
    Code.ROUTE_OVERLAP: "两条网的线共线重叠。改 RoutePlan 里的通道坐标，拉开 ≥2 格。",
    Code.ROUTE_ENDPOINT_OFF: "折线端点没落在引脚尖上。用 donor_info 的引脚偏移重算。",
    Code.ROUTE_UNROUTABLE: "找不到合法折线（引脚出线方向约束或空隙不够）。挪器件或手写 RoutePlan。",
    Code.NET_BROKEN: "Proteus 编译出的网络比意图少引脚。多半是线没搭上引脚尖。",
    Code.NET_SHORT: "意图网络被并进更大的网。检查是否有跨网共线或引脚插在段中间。",
    Code.PROTEUS_REJECTED: "Proteus 打开时弹窗。记下弹窗原文，多半是 CDB 记录结构问题。",
    Code.BAD_ARGUMENT: "参数不合法。",
    Code.INTERNAL: "内部错误，看 detail 里的异常。",
}


def ok(**kw):
    return dict({"ok": True}, **kw)


def fail(code, message="", **detail):
    return {"ok": False, "code": code,
            "message": message or HINTS.get(code, ""),
            "hint": HINTS.get(code, ""),
            "detail": detail}


def guard(fn):
    """把异常包成错误码，避免把 traceback 抛给调用方。"""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except KeyError as exc:
            return fail(Code.PIN_NOT_IN_SYMBOL, str(exc))
        except FileNotFoundError as exc:
            return fail(Code.BAD_ARGUMENT, f"文件不存在: {exc.filename}")
        except Exception as exc:                      # noqa: BLE001
            name = type(exc).__name__
            msg = str(exc)
            if "exit direction" in msg:
                return fail(Code.ROUTE_ENDPOINT_OFF, msg)
            if "overlap" in msg.lower():
                return fail(Code.ROUTE_OVERLAP, msg)
            if "junction" in msg.lower():
                return fail(Code.ROUTE_UNROUTABLE, msg)
            return fail(Code.INTERNAL, f"{name}: {msg}")
    return wrapper
