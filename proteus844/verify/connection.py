"""导线端点检查：每根线的端点到底接在哪。

规则（这是"看着像没接上"的量化判据）：

  · 每根导线有两个端点
  · 端点要么**正好落在某个引脚上**，要么和另一根线共端点（结点/拐角）
  · 都不满足 → 悬空

悬空不一定电气错（Proteus 按共端点判连接，悬空端就是没接），
但它一定意味着图上有一个"看起来连了其实没连"或者"线没画到位"的地方。

用法：
    python -m proteus844.verify.connection 工程.pdsprj
"""
import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from . import file_netlist as F          # noqa: E402


def _pin_points(project, donor=None):
    """所有引脚尖端坐标（native 整数）。

    donor：符号模板从哪读。默认用工程自己；但某些原语（LOGICSTATE 这类
    PACKAGE=NULL）从工程里读会抛异常 —— 那就必须借 donor，否则引脚集合残缺，
    会把接好的线误报成"悬空"（A/B 测试里踩到过）。
    """
    from . import reader as R
    from ..route.plan import _symbol_pins
    recs, _ = R.parse(project)
    pts = {}
    unresolved = set()
    for r in recs:
        if not r.get("ref"):
            continue
        try:
            pins = _symbol_pins(donor or project, r["device"])
        except Exception:                    # noqa: BLE001
            try:
                pins = _symbol_pins(project, r["device"])
            except Exception:                # noqa: BLE001
                unresolved.add(r.get("ref"))
                continue
        # donor 缺省时符号是从**工程自身**克隆的，vendor 已经把实例旋转算进去了；
        # 再按 rotation 转一次就是双重旋转（R14 竖放会因此误报悬空）。
        ang = 0 if donor is None else int(r.get("rotation", 0)) // 10
        for name, (dx, dy, ddx, ddy) in pins.items():
            if ang == 90:
                dx, dy = -dy, dx
            elif ang == 180:
                dx, dy = -dx, -dy
            elif ang == 270:
                dx, dy = dy, -dx
            pts[(r["x"] + int(round(dx * F.GRID if hasattr(F, 'GRID') else dx * 254000)),
                 r["y"] + int(round(dy * 254000)))] = f"{r['ref']}.{name}"
    _pin_points.unresolved = unresolved
    return pts


def _pin_dirs(project, donor=None):
    """引脚尖端 → 出线方向（单位向量）。"""
    from . import reader as R
    from ..route.plan import _symbol_pins
    recs, _ = R.parse(project)
    _pin_dirs._unresolved = set()
    out = {}
    for r in recs:
        if not r.get("ref"):
            continue
        try:
            pins = _symbol_pins(donor or project, r["device"])
        except Exception:                    # noqa: BLE001
            try:
                pins = _symbol_pins(project, r["device"])
            except Exception:                # noqa: BLE001
                _pin_dirs._unresolved.add(r.get("ref"))
                continue
        # donor 缺省时符号是从**工程自身**克隆的，vendor 已经把实例旋转算进去了；
        # 再按 rotation 转一次就是双重旋转（R14 竖放会因此误报悬空）。
        ang = 0 if donor is None else int(r.get("rotation", 0)) // 10
        for name, (dx, dy, ddx, ddy) in pins.items():
            if ang == 90:
                dx, dy, ddx, ddy = -dy, dx, -ddy, ddx
            elif ang == 180:
                dx, dy, ddx, ddy = -dx, -dy, -ddx, -ddy
            out[(r["x"] + int(round(dx * 254000)), r["y"] + int(round(dy * 254000)))] = (ddx, ddy)
    return out


def check(project, donor=None):
    """端点分类：落在引脚上 / 与别的线共端点 / 电源端子桩 / 真悬空。

    电源端子（VCC/GND）在引脚外 2 格挂符号时，vendor 会画一根 2 格的桩线，
    它的远端不是引脚 —— 那是**设计如此**，单独统计，不算悬空。
    真正要看的是"既不在引脚、也不共端点、也不是端子桩"的那几个。
    """
    recs, wires, nets = F.rebuild(project)
    pin_at = _pin_points(project, donor)
    unresolved = getattr(_pin_points, "unresolved", set())
    pin_dirs = _pin_dirs(project, donor)

    ends = collections.Counter()
    for start, pts in wires.items():
        ends[tuple(pts[0])] += 1
        ends[tuple(pts[-1])] += 1

    on_pin = shared = stub = 0
    dangling, off_grid_on_pin = [], []
    for pt, n in ends.items():
        gx, gy = pt[0] / 254000.0, pt[1] / 254000.0
        integral = abs(gx - round(gx)) < 1e-6 and abs(gy - round(gy)) < 1e-6
        if pt in pin_at:
            on_pin += 1
            if not integral:                   # 引脚本身就不在栅格上，这是对的位置
                off_grid_on_pin.append((round(gx, 2), round(gy, 2)))
            continue
        if n >= 2:
            shared += 1
            continue
        # 是不是"引脚外 2 格的电源端子桩"
        # 电源符号桩：沿引脚朝向 1~3 格都算（有的符号放 1 格，有的 2 格）
        is_stub = False
        for (px, py), (dx, dy) in pin_dirs.items():
            for k in (1, 2, 3):
                if (abs(pt[0] - (px + dx * k * 254000)) < 1
                        and abs(pt[1] - (py + dy * k * 254000)) < 1):
                    is_stub = True
                    break
            if is_stub:
                break
        if is_stub:
            stub += 1
            continue
        dangling.append({"point": pt, "grid": (round(gx, 2), round(gy, 2))})

    return {"wires": len(wires), "ends": sum(ends.values()),
            "ends_on_pin": on_pin, "ends_shared": shared,
            "terminal_stubs": stub,
            "off_grid_on_pin": off_grid_on_pin,
            "dangling": dangling,
            "unresolved_devices": sorted(x for x in unresolved if x),
            "partial": bool(unresolved) and not pin_at,
            "ok": not dangling and not unresolved}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m proteus844.verify.connection <工程.pdsprj>")
    donor = None
    if "--donor" in sys.argv:
        donor = sys.argv[sys.argv.index("--donor") + 1]
    r = check(sys.argv[1], donor)
    print(f"{r['wires']} 根导线 / {r['ends']} 个端点："
          f"引脚 {r['ends_on_pin']}，共端点 {r['ends_shared']}，"
          f"电源端子桩 {r['terminal_stubs']}，悬空 {len(r['dangling'])}"
          f"（引脚本身不在栅格上的 {len(r['off_grid_on_pin'])} 个属正常）")
    if r.get("unresolved_devices"):
        print(f"  ⚠ 这些器件取不到符号模板，它们的引脚没参与判定：{r['unresolved_devices']}")
    for d in r['dangling'][:10]:
        print(f"  悬空 @ {d['grid']}")
    for d in r["dangling"][:20]:
        print(f"  悬空 @ 格 {d['grid']}")
