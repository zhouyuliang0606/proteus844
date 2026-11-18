"""一键流程：图片 + 器件清单 → .pdsprj（含验收报告）。

模型只负责产出一份 `components.json`：
  [{"ref":"U1:D","device":"7400",
    "pin":"Y","tip_px":[204,60.5],          # 任选一个已知引脚尖（走符号预测）
    "pins":{"A":[149,52.5],"B":[149,69.5],"Y":[204,60.5]},   # 或直接给全部
    "bbox":[149,44,187,78]}]
其余（抽线、找点、建网、布线、写盘、验收）全自动。
"""
import json
import os
import sys

G = 254000


def _vendor():
    v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "ref844")
    if v not in sys.path:
        sys.path.insert(0, v)




def _layout_warnings(netlist, donor):
    """器件互相压住 = 画出来一定难看/看不懂，提前报。"""
    from .route.plan import pin_table
    tips = pin_table(netlist, donor)
    boxes = {}
    for (ref, name), (x, y, dx, dy) in tips.items():
        b = boxes.setdefault(ref, [x, y, x, y])
        b[0], b[1] = min(b[0], x), min(b[1], y)
        b[2], b[3] = max(b[2], x), max(b[3], y)
    refs = sorted(boxes)
    out = []
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            a, b = boxes[refs[i]], boxes[refs[j]]
            if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                out.append(f"器件重叠：{refs[i]} 与 {refs[j]}")
    return out

def _separate(netlist, donor, max_rounds=12):
    """把重合的引脚推开：同一点上有两个不同器件的引脚，就把后者下移一格。"""
    from .route.plan import pin_table
    moved = []
    for _ in range(max_rounds):
        tips = pin_table(netlist, donor)
        seen = {}
        clash = None
        for (ref, name), (x, y, dx, dy) in tips.items():
            key = (x, y)
            if key in seen and seen[key][0] != ref:
                clash = (seen[key][0], ref)
                break
            seen[key] = (ref, name)
        if clash is None:
            return moved
        target = next(c for c in netlist["components"] if c["ref"] == clash[1])
        target["y"] -= 1
        moved.append((clash[1], target["y"]))
    return moved



def _normalize(netlist, margin=10):
    """把整张图平移到图纸内：减去最小角，留 margin。比例尺放大后必须做，否则全跑图外。"""
    comps = netlist["components"]
    if not comps:
        return netlist
    xs = [c["x"] for c in comps]
    ys = [c["y"] for c in comps]
    dx, dy = min(xs) - margin, min(ys) - margin
    for c in comps:
        c["x"] -= dx
        c["y"] -= dy
    return netlist


def _grid_components(components, anchors, ppg, snap=2):
    """snap：坐标吸附到 snap 的倍数。密脚器件（数码管 1 格间距）需要 ≥2，
    否则车道和引脚挤在同一格上，相邻网会共用拐点被并成一个网。"""
    def s(v):
        return int(round(v / snap)) * snap if snap > 1 else int(round(v))
    return [{"ref": c["ref"], "device": c["device"],
             "value": c.get("value") or c["device"],
             "x": s(anchors[c["ref"]][0] / ppg),
             "y": s(-anchors[c["ref"]][1] / ppg),   # 图像 y 向下，Proteus y 向上
             "rotation": int(c.get("rotation", 0))}  # 必须透传，竖放元件全靠它
            for c in components]


def anchors_from_pins(components, donor, ppg):
    """由每个器件已知引脚尖反推锚点（rotation-aware，y 翻转）"""
    from .route.plan import _symbol_pins, _rot
    anchors = {}
    for c in components:
        xy = {n: tuple(v) for n, v in c["pins"].items()}
        offs = _symbol_pins(donor, c["device"])
        ang = int(c.get("rotation", 0))
        known = next(n for n in xy if n in offs)
        dx, dy = _rot(offs[known][0], offs[known][1],
                      (offs[known][2], offs[known][3]), ang)[:2]
        anchors[c["ref"]] = (xy[known][0] - dx * ppg, xy[known][1] + dy * ppg)
    return anchors


def assemble(components, nets, out, donor, ppg, image=None, tol=2.5, verbose=True):
    """已有网表 → 工程。识别由调用方负责，这里只做布局消解/布线/写盘/验收。"""
    from .route import plan as RP
    from .build import writer
    from . import validate as V
    from .verify import file_netlist as F

    log = []

    def say(m):
        if verbose:
            print(m)
        log.append(m)

    from .verify import donor_check as DC
    dc = DC.check(donor)
    if not dc["empty"]:
        say(f"[0] 提示：donor 里有 {dc['components']} 个器件 / {dc['wires']} 条导线"
            f"（不会进输出，已实测）")

    anchors = anchors_from_pins(components, donor, ppg)
    # 教材图比例常比 Proteus 符号密（器件在格空间里会叠住）→ 逐级放大布局
    for shrink in (1.0, 0.85, 0.7, 0.6, 0.5, 0.42, 0.35, 0.3):
        use_ppg = ppg * shrink
        a2 = anchors_from_pins(components, donor, use_ppg)
        trial = {"components": _grid_components(components, a2, use_ppg), "nets": []}
        if not _layout_warnings(trial, donor):
            break
    if shrink != 1.0:
        say(f"[0] 布局放大：px_per_grid {ppg} → {round(use_ppg,2)}（教材比例太密，器件会叠住）")
        ppg = use_ppg
        anchors = a2
    # 电源/地不拉线：按惯例每个引脚挂一个符号（拉线会横穿全图，把所有车道切断）
    SUPPLY = {"GND": "ground", "GNDA": "ground", "VSS": "ground",
              "VCC": "power", "VDD": "power", "+5V": "power", "+3V3": "power"}
    signal, terminals = [], []
    for i, n in enumerate(nets):
        name = n.get("name", f"N{i+1}")
        if name.upper() in SUPPLY:
            for pin in n["pins"]:
                terminals.append({"kind": SUPPLY[name.upper()], "name": name,
                                  "pin": list(pin)})
        else:
            signal.append({"name": name, "pins": [list(p) for p in n["pins"]]})
    netlist = {"components": _grid_components(components, anchors, ppg),
               "nets": signal, "terminals": terminals}
    say(f"[1] 网表：{len(netlist['components'])} 器件 / {len(netlist['nets'])} 信号网 "
        f"+ {len(terminals)} 个电源符号（不拉线）")

    moved = _separate(netlist, donor)
    if moved:
        say(f"[2] 推开重合器件 {len(moved)} 次：" +
            ", ".join(f"{r}→y={y}" for r, y in moved[:4]))
    for w in _layout_warnings(netlist, donor):
        say(f"[2.5] ⚠ {w}")

    v = V.validate(netlist, donor)
    if not v.get("ok"):
        say(f"[3] ❌ 校验失败 {v.get('code')}: {v.get('message')}")
        for e in (v.get("detail") or {}).get("errors", [])[:5]:
            say("    · " + e["message"])
        return {"ok": False, "stage": "validate", "detail": v, "netlist": netlist}

    say("[3] 校验通过")
    # 密集图（如 7 条平行网）在原始比例尺下扇出空间不足 → 逐级放大重试
    plan_doc, probs = None, []
    for factor in (1.0, 0.8, 0.65, 0.55, 0.45, 0.38, 0.3):
        use = ppg * factor
        a2 = anchors_from_pins(components, donor, use)
        trial_nl = {"components": _grid_components(components, a2, use),
                    "nets": netlist["nets"],
                    "terminals": netlist.get("terminals", [])}   # ★ 丢了它就一个电源符号都不画
        try:
            trial_plan = RP.plan(trial_nl, donor)
        except ValueError as exc:
            say(f"    · 比例尺 {use:.2f} 规划失败：{str(exc)[:60]}")
            continue
        trial_probs = RP.check(trial_plan)
        trial_hard = [p for p in trial_probs
                      if "平行间距" not in p and "共线重叠" not in p]
        if not trial_hard:
            trial_nl = _normalize(trial_nl)
            trial_plan = RP.plan(trial_nl, donor)
            trial_probs = RP.check(trial_plan)
            trial_hard = [p for p in trial_probs
                          if "平行间距" not in p and "共线重叠" not in p]
            if trial_hard:
                continue
            plan_doc, probs, netlist = trial_plan, trial_probs, trial_nl
            if factor != 1.0:
                say(f"[3.5] 布局放大到 px_per_grid={use:.2f}（原始比例扇出空间不足）")
            break
        say(f"    · 比例尺 {use:.2f} 仍有 {len(trial_hard)} 处重叠")
    if plan_doc is None:
        say("[4] ❌ 所有比例尺都规划失败")
        return {"ok": False, "stage": "plan", "problems": probs,
                "netlist": netlist}
    n_par = len([p for p in probs if "平行间距" in p])
    n_ovl = len([p for p in probs if "共线重叠" in p])
    say(f"[4] 布线规划通过：平行间距提示 {n_par} 处，"
        f"跨网共线重叠 {n_ovl} 处" + ("（只是观感，不会连通）" if n_ovl else ""))

    build_res = writer.build(netlist, plan_doc, donor, out)
    import os
    say(f"[5] 已写出 {out}（{os.path.getsize(out)} B）")
    for e in build_res.get("terminal_errors", []):
        say(f"    ⚠ 终端没加上：{e['terminal']}")

    if image:
        from .verify import pin_dirs as PD
        dirs = PD.compare(image, out, netlist, components, donor, ppg)
        say(f"[6] 识别校验：{dirs['checked_pins']} 引脚，方向不一致 {dirs['mismatched']} 个")
        for dd in dirs["details"][:4]:
            say(f"    · {tuple(dd['pin'])}  图上 {dd['image']}  画里 {dd['project']}")
    else:
        dirs = None

    d = F.diff(netlist, out)
    say(f"[7] 文件级验收：{d['summary']} → {'✅ 一致' if d['ok'] else '❌ 不一致'}")
    xs = [c["x"] for c in netlist["components"]]
    ys = [c["y"] for c in netlist["components"]]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    say(f"[8] 布局 {w}x{h} 格 → " + ("A4 装得下" if w <= 128 and h <= 66
                                       else "⚠ 超出 A4（约 132x70）"))
    say("[9] ⚠ 截图后用 verify.screenshot_check 检查斜线（>0.15 即有问题）")
    return {"ok": d["ok"], "stage": "done", "path": out, "netlist": netlist,
            "plan": plan_doc, "verify": d, "pin_dirs": dirs, "log": log}



SUPPLY_KIND = {"GND": "ground", "GNDA": "ground", "VSS": "ground",
               "VCC": "power", "VDD": "power", "+5V": "power", "+3V3": "power"}


def split_supply(netlist):
    """把 VCC/GND 这类网从 nets 里拿出来变成 terminals。

    电源网动辄十几脚，做成星形结点是画不出来的 —— 必须挂符号。
    """
    signal, terms = [], list(netlist.get("terminals") or [])
    for n in netlist.get("nets", []):
        name = (n.get("name") or "").upper()
        if name in SUPPLY_KIND:
            for pin in n["pins"]:
                terms.append({"kind": SUPPLY_KIND[name], "name": n["name"],
                              "pin": list(pin)})
        else:
            signal.append({"name": n.get("name"), "pins": [list(p) for p in n["pins"]]})
    out = dict(netlist)
    out["nets"] = signal
    out["terminals"] = terms
    return out


def build_from_topology(netlist, donor, out, verbose=True, max_rounds=4):
    """只给拓扑（ref/device/value + nets），自动布局并生成工程。"""
    from .route import place as PL
    from .route import plan as RP
    from .build import writer
    from .verify import file_netlist as F

    log = []

    def say(m):
        if verbose:
            print(m)
        log.append(m)

    nl = split_supply(netlist)
    say(f"[1] 拓扑：{len(nl['components'])} 器件 / {len(nl['nets'])} 信号网"
        f" + {len(nl['terminals'])} 电源端子")

    gaps = [(8, 6), (12, 10), (16, 14), (20, 18), (26, 22)]
    last = None
    for i, (gx, gy) in enumerate(gaps[:max_rounds]):
        placed = PL.place(nl, donor, gap_x=gx, gap_y=gy)
        xs = [c["x"] for c in placed["components"]]
        ys = [c["y"] for c in placed["components"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        try:
            doc = RP.plan(placed, donor)
            writer.build(placed, doc, donor, out)
        except Exception as exc:                       # noqa: BLE001
            say(f"[2] 间距 {gx}/{gy} 布局 {w}×{h} 失败：{type(exc).__name__}: {str(exc)[:60]}")
            last = exc
            continue
        d = F.diff(nl, out)
        say(f"[2] 间距 {gx}/{gy} 布局 {w}×{h} → 验收 {d['summary']}")
        if d["ok"]:
            try:
                from .verify import sheet as SH
                sh = SH.fit_to_content(out)
                say(f"[2.5] 图纸调到 {sh['to'][0]}×{sh['to'][1]} 格")
            except Exception as exc:               # noqa: BLE001
                say(f"[2.5] 图纸调整跳过：{exc}")
            say(f"[3] 已写出 {out}")
            return {"ok": True, "path": out, "layout": [w, h], "gaps": [gx, gy],
                    "verify": d, "netlist": placed, "plan": doc, "log": log}
        last = ValueError(str(d["summary"]))
    say(f"[2] 所有间距都失败：{last}")
    return {"ok": False, "stage": "place", "error": str(last), "log": log}


def estimate_ppg(components, donor):
    """用 donor 符号的格数反推 px_per_grid：每器件取一次跨度比，取中位数。"""
    from .route.plan import _symbol_pins
    import statistics
    ratios = []
    for c in components:
        xy = c.get("pins") or {}
        if len(xy) < 2:
            continue
        offs = _symbol_pins(donor, c["device"])
        names = [n for n in xy if n in offs]
        if len(names) < 2:
            continue
        gx = max(offs[n][0] for n in names) - min(offs[n][0] for n in names)
        gy = max(offs[n][1] for n in names) - min(offs[n][1] for n in names)
        px = max(v[0] for v in xy.values()) - min(v[0] for v in xy.values())
        py = max(v[1] for v in xy.values()) - min(v[1] for v in xy.values())
        if gx > 0 and px > 0:
            ratios.append(px / gx)
        if gy > 0 and py > 0:
            ratios.append(py / gy)
    return round(statistics.median(ratios), 3) if ratios else None


def draw(image, out, donor, components, ppg, tol=2.5, verbose=True,
         segments=None, threshold=140, min_len=12):
    from .recognize import segments as S, junctions as J, pins as P
    from .netlist import trace as T
    from .route import plan as RP
    from .build import writer
    from . import validate as V
    from .verify import file_netlist as F
    import numpy as np
    from PIL import Image

    log = [] if verbose else None

    def say(msg):
        if verbose:
            print(msg)
        if log is not None:
            log.append(msg)

    # 1) 几何
    im = Image.open(image).convert("L")
    ink = np.array(im) < threshold
    if segments:                       # 用调用方给的线段（模型可能已手工补过）
        segs = segments
        raw = {"horizontal": [s for s in segs if s["a"][1] == s["b"][1]],
               "vertical": [s for s in segs if s["a"][0] == s["b"][0]]}
    else:
        raw = S.extract(ink, min_len=min_len)
        segs = S.as_segments(raw)
    dots = J.detect(ink)
    say(f"[1] 线段 {len(segs)} 条（横 {len(raw['horizontal'])} / 竖 {len(raw['vertical'])}），"
        f"结点 {len(dots)} 个（peak≥2.1 的 {sum(1 for d in dots if d['peak'] >= 2.1)} 个）"
        + ("  [线段来自调用方]" if segments else ""))

    # 2) 引脚尖
    if all("pins" in c for c in components):
        from .route.plan import _symbol_pins, _rot
        tips, anchors = [], {}
        for c in components:
            xy = {n: tuple(v) for n, v in c["pins"].items()}
            tips += [{"ref": c["ref"], "pin": n, "tip": v} for n, v in xy.items()]
            # 锚点 = 引脚尖 − 符号偏移。两处都不能忘：
            #   a) y 要翻转（图像 y 向下，Proteus y 向上）
            #   b) 偏移要按 rotation 旋转，否则竖放元件的锚点全错、会互相压住
            offs = _symbol_pins(donor, c["device"])
            ang = int(c.get("rotation", 0))
            known = next(n for n in xy if n in offs)
            dx, dy = _rot(offs[known][0], offs[known][1],
                          (offs[known][2], offs[known][3]), ang)[:2]
            anchors[c["ref"]] = (xy[known][0] - dx * ppg, xy[known][1] + dy * ppg)
    else:
        pred = P.predict(components, donor, ppg)
        tips, anchors = [], {}
        for c in pred:
            tips += [{"ref": c["ref"], "pin": n, "tip": v} for n, v in c["pins"].items()]
            anchors[c["ref"]] = c["anchor_px"]
    say(f"[2] 引脚尖 {len(tips)} 个，器件 {len(components)} 个")

    # 3) 建网
    boxes = [c["bbox"] for c in components if c.get("bbox")]
    res = T.trace(segs, dots, tips, tol=tol, exclude_boxes=boxes)
    say(f"[3] 建网：{len(res['nets'])} 个网，未决 {len(res['unresolved'])} 项")
    for u in res["unresolved"][:5]:
        say(f"    · {u['kind']}: {u.get('pin')}")

    # 4) 组装网表（坐标用格）
    netlist = {"components": _grid_components(components, anchors, ppg),
               "nets": [{"name": f"N{i+1}", "pins": [list(p) for p in n["pins"]]}
                        for i, n in enumerate(res["nets"])],
               "terminals": []}
    say(f"[4] 网表：{len(netlist['components'])} 器件 / {len(netlist['nets'])} 网")

    # 4.5) 布局消解（教材符号比例 ≠ Proteus 符号比例，必须推开重合的引脚）
    moved = _separate(netlist, donor)
    if moved:
        say(f"[4.5] 推开重合器件 {len(moved)} 次："
            + ", ".join(f"{r}→y={y}" for r, y in moved[:4]))

    # 4.6) 布局重叠检查（画出来好不好看，网表看不出来）
    layout_warn = _layout_warnings(netlist, donor)
    for w in layout_warn:
        say(f"[4.6] ⚠ {w}")

    # 5) 校验
    v = V.validate(netlist, donor)
    if not v.get("ok"):
        say(f"[5] ❌ 校验失败 {v.get('code')}: {v.get('message')}")
        return {"ok": False, "stage": "validate", "detail": v, "netlist": netlist}
    say("[5] 校验通过")

    # 6) 布线 + 生成
    plan_doc = RP.plan(netlist, donor)
    probs = RP.check(plan_doc)
    hard = [p for p in probs if "平行间距" not in p]
    warn = [p for p in probs if "平行间距" in p]
    if hard:
        say(f"[6] ❌ 布线自检失败 {len(hard)} 处")
        for p in hard[:5]:
            say("    · " + p)
        return {"ok": False, "stage": "plan", "problems": hard,
                "netlist": netlist, "plan": plan_doc}
    say(f"[6] 布线规划通过（可读性提示 {len(warn)} 处）")

    build_res = writer.build(netlist, plan_doc, donor, out)
    say(f"[7] 已写出 {out}（{os.path.getsize(out)} B）")
    for e in build_res.get("terminal_errors", []):
        say(f"    ⚠ 终端没加上：{e['terminal']}")

    # 7) 识别校验：逐引脚比对出线方向（能抓 rotation/朝向错，netdiff 抓不到）
    from .verify import pin_dirs as PD
    dirs = PD.compare(image, out, netlist, components, donor, ppg)
    say(f"[7.5] 识别校验：{dirs['checked_pins']} 个引脚，"
        f"出线方向不一致 {dirs['mismatched']} 个"
        + ("  ⚠ 多半是 rotation 设错" if dirs["mismatched"] > 1 else ""))
    for dd in dirs["details"][:4]:
        say(f"    · {tuple(dd['pin'])}  图上 {dd['image']}  画里 {dd['project']}")

    # 7) 文件级验收
    d = F.diff(netlist, out)
    say(f"[8] 文件级验收：{d['summary']} → {'✅ 一致' if d['ok'] else '❌ 不一致'}")
    for n in d["nets"]:
        if n["status"] != "OK":
            say(f"    · {n['status']} {n['net']} {n.get('extra_pins') or n.get('found')}")

    if d["ok"]:
        say("[9] ⚠ 交付前务必看渲染图（rotation/布局/斜线这三类错 netdiff 都抓不到）：")
        say("    在 Proteus 里截图后跑 proteus844.verify.screenshot_check —— "
            "斜线能量 > 0.15 就是有问题")
    xs = [c["x"] for c in netlist["components"]]
    ys = [c["y"] for c in netlist["components"]]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w > 128 or h > 66:
        say(f"[9] ⚠ 布局 {w}x{h} 格，超出 A4 图纸（约 132x70）")
    else:
        say(f"[9] 布局 {w}x{h} 格，A4 装得下")
    return {"ok": d["ok"], "stage": "done", "path": out,
            "netlist": netlist, "plan": plan_doc, "verify": d,
            "layout_warnings": layout_warn, "pin_dirs": dirs, "log": log}
