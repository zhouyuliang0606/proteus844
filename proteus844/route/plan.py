"""布线规划：给网表算出「用什么通道、结点在哪、每条支线怎么走」。

规则（SKILL 1.5 节）：
  1. 两脚网 → 沿引脚出线方向迈一格，再正交折到对面；走廊冲突时换偏移重试
  2. 多脚网 → 星形：所有支线汇到一个结点 J
  3. 通道按**跨度降序**分配，间距 ≥2 格，离引脚列 ≥2 格
  4. **必须遵守引脚出线方向**（Proteus 会校验，违反报 Wire violates a pin exit direction）
  5. 不允许跨网共线重叠（密集电路上最容易踩，7 条平行网会全挤在一条竖线上）

输出 RoutePlan：
  两脚网: {"name","junction":null,"path":[[x,y],...],"pins":[[ref,pin],...]}
  多脚网: {"name","junction":[x,y],"branches":[{"pin":[ref,pin],"points":[...]}]}
"""
from collections import defaultdict

STUB = 1                      # 出线段长度（格）
OVERLAP_WARN = []             # 走廊用尽时降级记录的共线警告
CORRIDORS = (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 8, -8,
             10, -10, 12, -12, 14, -14, 16, -16, 18, -18, 20, -20)


def _symbol_pins(donor, device):
    """{引脚名: (dx, dy, dx_dir, dy_dir)} —— 单位格，含出线方向"""
    import os
    import sys
    vendor = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "vendor", "ref844")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from component_codec import Circuit
    cache = getattr(_symbol_pins, "_c", {})
    if (donor, device) in cache:
        return cache[(donor, device)]
    c = Circuit(donor)
    ref = "P1:A"
    c.add(device=device, ref=ref, value=device, x=0, y=0)
    G = 254000
    out = {}
    for p in c.pins(ref):
        x, y = p["position"]
        d = p.get("direction") or (0, 0)
        out[p["name"]] = (round(x / G), round(y / G), int(d[0]), int(d[1]))
    cache[(donor, device)] = out
    _symbol_pins._c = cache
    return out


def _rot(dx, dy, dd, angle):
    """把偏移和方向按 angle 度逆时针旋转（Proteus 的 rotation 是度）"""
    a = int(angle) % 360
    if a == 0:
        return dx, dy, dd[0], dd[1]
    if a == 90:
        return -dy, dx, -dd[1], dd[0]
    if a == 180:
        return -dx, -dy, -dd[0], -dd[1]
    if a == 270:
        return dy, -dx, dd[1], -dd[0]
    raise ValueError(f"只支持 0/90/180/270 度，收到 {angle}")


def pin_table(netlist, donor):
    """{(ref,pin): (x, y, dx, dy)} —— 绝对格坐标 + 出线方向（已按 rotation 旋转）"""
    tips = {}
    for comp in netlist["components"]:
        offs = _symbol_pins(donor, comp["device"])
        ang = comp.get("rotation", 0)
        for name, (dx, dy, ddx, ddy) in offs.items():
            rdx, rdy, rddx, rddy = _rot(dx, dy, (ddx, ddy), ang)
            tips[(comp["ref"], name)] = (comp["x"] + rdx, comp["y"] + rdy, rddx, rddy)
    return tips


def _dir(p, q):
    """从 p 指向 q 的方向（与库里的 _direction(a,b) 一致）"""
    return ((q[0] > p[0]) - (q[0] < p[0]), (q[1] > p[1]) - (q[1] < p[1]))


def _valid(pts):
    """无重复点、无零长段、无 180° 回折"""
    seen = set()
    for i, p in enumerate(pts):
        if i and tuple(p) == tuple(pts[i - 1]):
            return False
        if tuple(p) in seen:
            return False
        seen.add(tuple(p))
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        if a[0] == b[0] == c[0] and (b[1] - a[1]) * (c[1] - b[1]) < 0:
            return False
        if a[1] == b[1] == c[1] and (b[0] - a[0]) * (c[0] - b[0]) < 0:
            return False
    return True


def _simplify(pts):
    """去掉与前后共线的中间顶点"""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        if not ((a[1] == b[1] == c[1]) or (a[0] == b[0] == c[0])):
            out.append(b)
    out.append(pts[-1])
    return out


def _clean(pts, a_dir, b_dir):
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    out = _simplify(out)
    return out



def _hit_foreign(path, blocked):
    """路径上（含中间格）是否落到了别人的引脚坐标上"""
    for a, b in zip(path, path[1:]):
        if a[0] == b[0]:                      # 竖段
            y0, y1 = sorted((a[1], b[1]))
            for y in range(int(y0), int(y1) + 1):
                if (a[0], y) in blocked:
                    return (a[0], y)
        elif a[1] == b[1]:                    # 横段
            x0, x1 = sorted((a[0], b[0]))
            for x in range(int(x0), int(x1) + 1):
                if (x, a[1]) in blocked:
                    return (x, a[1])
    return None


def _route_2pin(a, da, b, db, k=0, blocked=frozenset()):
    """k = 走廊偏移。返回 (path) 或 None。
    need = (a_stub, b_stub, a_stub2, b_stub2) 由 plan() 传入，一般不用。"""
    for stub in (STUB, 0):
        p1 = (a[0] + da[0] * stub, a[1] + da[1] * stub) if (da != (0, 0) and stub) else a
        p2 = (b[0] + db[0] * stub, b[1] + db[1] * stub) if (db != (0, 0) and stub) else b
        cands = []
        if k == 0:
            if p1[0] == p2[0] or p1[1] == p2[1]:
                cands.append([a, p1, p2, b])
            cands += [[a, p1, (p2[0], p1[1]), p2, b],
                      [a, p1, (p1[0], p2[1]), p2, b]]
        else:
            if da[0] != 0:
                cands.append([a, p1, (p1[0], a[1] + k), (p2[0], a[1] + k), p2, b])
            elif da[1] != 0:
                cands.append([a, p1, (a[0] + k, p1[1]), (a[0] + k, p2[1]), p2, b])
            else:
                cands.append([a, (a[0] + k, a[1]), (a[0] + k, b[1]), b])
        for pts in cands:
            clean = _clean(pts, da, db)
            if len(clean) < 2:
                continue
            if not (_valid(clean) and tuple(clean[-1]) == tuple(b)):
                continue
            if tuple(da) != (0, 0) and _dir(clean[0], clean[1]) != tuple(da):
                continue
            if tuple(db) != (0, 0) and _dir(clean[-1], clean[-2]) != tuple(db):
                continue
            if blocked and _hit_foreign(clean, blocked):
                continue                       # 穿过别人的引脚 → 换一条
            return [list(p) for p in clean]
    return None


def _ov(p1, p2, q1, q2):
    """轴对齐线段重叠长度（>0 即共线冲突）"""
    if p1[1] == p2[1] == q1[1] == q2[1]:
        return min(max(p1[0], p2[0]), max(q1[0], q2[0])) - \
               max(min(p1[0], p2[0]), min(q1[0], q2[0]))
    if p1[0] == p2[0] == q1[0] == q2[0]:
        return min(max(p1[1], p2[1]), max(q1[1], q2[1])) - \
               max(min(p1[1], p2[1]), min(q1[1], q2[1]))
    return 0



def separate_pins(netlist, donor, min_gap=2, max_rounds=40):
    """把不同器件之间间距 < min_gap 的引脚沿 y 推开。返回挪动记录。"""
    moved = []
    for _ in range(max_rounds):
        tips = pin_table(netlist, donor)
        coords = {}
        clash = None
        for (ref, name), (x, y, _, _) in tips.items():
            key = (int(x), int(y))
            if key in coords and coords[key][0] != ref:
                clash = (coords[key][0], ref)
                break
            coords[key] = (ref, name)
        if clash is None:
            # 没有完全重合，再查 1 格内的面对面
            near = None
            items = list(tips.items())
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    (r1, n1), v1 = items[i]
                    (r2, n2), v2 = items[j]
                    if r1 == r2:
                        continue
                    if (abs(v1[0] - v2[0]) + abs(v1[1] - v2[1])) < min_gap:
                        near = (r1, r2)
                        break
                if near:
                    break
            if near is None:
                return moved
            clash = near
        target = next(c for c in netlist["components"] if c["ref"] == clash[1])
        target["y"] -= min_gap
        moved.append((clash[1], target["y"]))
    return moved



def _declutter(out, tips, max_rounds=8):
    """对跨网共线重叠的两脚网，拿全量线段当障碍重新走一遍。"""
    def segs_of(net):
        pts = net.get("path") or []
        return [(tuple(a), tuple(b)) for a, b in zip(pts, pts[1:])] if pts else []

    fixed = 0
    for _ in range(max_rounds):
        clashes = []
        nets = [n for n in out if n.get("path")]
        for i in range(len(nets)):
            for j in range(i + 1, len(nets)):
                for p1, q1 in segs_of(nets[i]):
                    for p2, q2 in segs_of(nets[j]):
                        if _ov(p1, q1, p2, q2) > 0:
                            clashes.append((nets[i]["name"], nets[j]["name"]))
        if not clashes:
            return fixed

        order_idx = {n["name"]: i for i, n in enumerate(out)}
        name = max(clashes[0], key=lambda nm: order_idx.get(nm, 0))
        target = next((n for n in out if n["name"] == name), None)
        if target is None:
            return fixed
        pins = [tuple(p) for p in target["pins"]]
        if len(pins) != 2:
            # 多脚网：平移星形结点（连同竖直段）试试
            jx = target["junction"][0]
            others_m = [(tuple(p), tuple(q)) for n in out if n["name"] != name
                        for p, q in segs_of(n)]
            moved = False
            for d in (2, -2, 4, -4, 6, -6, 8, -8, 10, -10, 12, -12):
                trial = []
                for br in target["branches"]:
                    pts = [[x + d if x == jx else x, y] for x, y in br["points"]]
                    trial.append({"pin": br["pin"], "points": pts})
                segs = [(tuple(a2), tuple(b2)) for br in trial
                        for a2, b2 in zip(br["points"], br["points"][1:])]
                if any(_ov(p2, q2, r, t) > 0 for p2, q2 in segs for r, t in others_m):
                    continue
                if any(tuple(v) in (r, t) for v in
                       [pt for br in trial for pt in br["points"]] for r, t in others_m):
                    continue
                target["branches"] = trial
                target["junction"] = [jx + d, target["junction"][1]]
                moved = True
                break
            if not moved:
                return fixed
            fixed += 1
            continue
        a, b = tips[pins[0]], tips[pins[1]]
        others = [(tuple(p), tuple(q)) for n in out if n["name"] != name
                  for p, q in segs_of(n)]

        best = None
        for k in CORRIDORS + tuple(range(-30, 31)):
            cand = _route_2pin(a[:2], a[2:], b[:2], b[2:], k=k)
            if cand is None:
                continue
            bad = any(_ov(tuple(p), tuple(q), r, t) > 0
                      for p, q in zip(cand, cand[1:]) for r, t in others)
            shared = any(tuple(v) in (r, t) for v in cand for r, t in others)
            if not bad and not shared:
                best = cand
                break
        if best is None:
            return fixed
        target["path"] = best
        fixed += 1
    return fixed


def plan(netlist, donor, min_spacing=2):
    OVERLAP_WARN.clear()
    separate_pins(netlist, donor)          # 先把挨太近的引脚推开，否则可能无解
    tips = pin_table(netlist, donor)
    all_pins = {(int(t[0]), int(t[1])) for t in tips.values()}
    used_ch, out = [], []
    used_segs = []            # [(netname, p, q)] —— 已占用线段

    def conflicts(path):
        for p, q in zip(path, path[1:]):
            for name2, r, s in used_segs:
                if _ov(tuple(p), tuple(q), r, s) > 0:
                    return name2
        return None

    def claim(name, path):
        for p, q in zip(path, path[1:]):
            used_segs.append((name, tuple(p), tuple(q)))

    jobs = []
    for net in netlist.get("nets", []):
        pins = [tuple(p) for p in net["pins"]]
        miss = [p for p in pins if p not in tips]
        if miss:
            raise KeyError(f"网 {net.get('name')} 引脚查不到坐标: {miss}")
        pts = [tips[p][:2] for p in pins]
        ys, xs = [p[1] for p in pts], [p[0] for p in pts]
        jobs.append({"name": net.get("name", "?"), "pins": pins,
                     "vspan": max(ys) - min(ys), "xs": xs, "ys": ys})

    # 扇出识别：两端列相同、数量 >=3 的两脚网，各分一条竖车道
    lanes = {}
    groups = defaultdict(list)
    for job in jobs:
        if len(job["pins"]) != 2:
            continue
        pa, pb = tips[job["pins"][0]][:2], tips[job["pins"][1]][:2]
        (lx, ly), (rx, ry) = sorted((pa, pb))
        groups[(round(lx), round(rx))].append((job["name"], ly, ry))
    for (lx, rx), members in groups.items():
        if len(members) < 3 or rx - lx < len(members) + 1:
            continue
        members.sort(key=lambda m: (m[1] + m[2]) / 2)
        span = rx - lx - 1
        for i, (name, _, _) in enumerate(members):
            lanes[name] = lx + 1 + round(i * (span - 1) / max(1, len(members) - 1))

    # 多脚网先占通道（跨度降序），两脚网后填，避免两个大网抢同一条通道
    for job in sorted(jobs, key=lambda j: (-len(j["pins"]), -j["vspan"])):
        pins = job["pins"]
        if len(pins) == 2:
            a, b = tips[pins[0]], tips[pins[1]]
            path, why = None, None
            if job["name"] in lanes:                    # 扇出：走指定车道
                lane = lanes[job["name"]]
                cand = _clean([[a[0], a[1]], [lane, a[1]], [lane, b[1]], [b[0], b[1]]],
                              a[2:], b[2:])
                ok = (len(cand) >= 2 and _valid(cand)
                      and tuple(cand[-1]) == tuple(b[:2])
                      and (tuple(a[2:]) == (0, 0) or _dir(cand[0], cand[1]) == tuple(a[2:]))
                      and (tuple(b[2:]) == (0, 0) or _dir(cand[-1], cand[-2]) == tuple(b[2:])))
                if ok and conflicts(cand) is None and not any(
                        tuple(v) in (r, t_)
                        for v in cand
                        for nm, r, t_ in used_segs if nm != job["name"]):
                    path = cand
            # 车道优先：扇出已经算好了专属车道，就别再让通用走廊覆盖它。
            # 之前这里无条件跑 CORRIDORS，算好的车道被覆盖，
            # 1 格栅距的扇出会贴着相邻脚行跑、堵死后面的网（子代实测：N18 无解）。
            best, best_cost = None, None
            if path is None:
                for k in CORRIDORS:
                    cand = _route_2pin(a[:2], a[2:], b[:2], b[2:], k=k)
                    if cand is None:
                        continue
                    shared = any(tuple(v) in (r, t_)
                                 for v in cand
                                 for nm, r, t_ in used_segs if nm != job["name"])
                    clash = conflicts(cand)
                    if clash is None and not shared:
                        path, why = cand, None
                        break
                    if shared:
                        why = "共端点"
                        continue
                    cost = sum(_ov(tuple(p), tuple(q), r, t_)
                               for p, q in zip(cand, cand[1:])
                               for nm, r, t_ in used_segs if nm != job["name"])
                    if best_cost is None or cost < best_cost:
                        best, best_cost, why = cand, cost, clash
            if path is None:
                if best is None:
                    raise ValueError(f"网 {job['name']} 完全无法走线（无合法正交路径）")
                path = best
                OVERLAP_WARN.append(f"{job['name']} 与 {why} 共线（冲突最小的走廊）")
            claim(job["name"], path)
            out.append({"name": job["name"], "junction": None,
                        "path": path, "pins": [list(p) for p in pins]})
            continue

        xs, ys = job["xs"], job["ys"]
        lo, hi = min(xs) + 1, max(xs) - 1
        ch = None
        for cand in range(lo, hi + 1):
            if any(abs(cand - u) < min_spacing for u in used_ch):
                continue
            if any(abs(cand - x) < min_spacing for x in set(xs)):
                continue
            ch = cand
            break
        if ch is None:
            ch = lo if lo <= hi else min(xs) - 1
            while any(abs(ch - u) < min_spacing for u in used_ch):
                ch -= min_spacing
        used_ch.append(ch)

        jy = sorted(ys)[len(ys) // 2]
        J = [ch, jy]
        branches = []
        for pin in pins:
            x, y, ddx, ddy = tips[pin]
            path = [[x, y]]
            stub = (x + ddx * STUB, y + ddy * STUB) if (ddx, ddy) != (0, 0) else (x, y)
            if stub != (x, y):
                path.append([stub[0], stub[1]])
            behind = ((ddx != 0 and (ch - stub[0]) * ddx < 0)
                      or (ddy != 0 and (jy - stub[1]) * ddy < 0))
            if behind:                      # 通道在引脚背后：先横出去再绕回来，避免回折
                off = jy + (2 if jy >= stub[1] else -2)
                path.append([stub[0], off])
                path.append([ch, off])
                path.append([ch, jy])
            elif stub[1] != jy:
                if stub[0] != ch:
                    path.append([ch, stub[1]])
                path.append([ch, jy])
            elif stub[0] != ch:
                path.append([ch, jy])
            if path[-1] != [ch, jy]:
                path.append([ch, jy])
            path = _clean(path, (0, 0), (0, 0)) or path
            for shift in (0, 2, -2, 4, -4, 6, -6, 8, -8):
                ch2 = ch + shift
                p2 = [[x, y]]
                stub2 = (x + ddx * STUB, y + ddy * STUB) if (ddx, ddy) != (0, 0) else (x, y)
                if stub2 != (x, y):
                    p2.append([stub2[0], stub2[1]])
                if stub2[1] != jy:
                    if stub2[0] != ch2:
                        p2.append([ch2, stub2[1]])
                    p2.append([ch2, jy])
                elif stub2[0] != ch2:
                    p2.append([ch2, jy])
                if p2[-1] != [ch2, jy]:
                    p2.append([ch2, jy])
                p2 = _clean(p2, (0, 0), (0, 0)) or p2
                if not any(tuple(v) in (r, t_)
                           for v in p2
                           for nm, r, t_ in used_segs if nm != job["name"]):
                    path = p2
                    break
            branches.append({"pin": list(pin), "points": path})
            claim(job["name"], path)
        junc = branches[0]["points"][-1] if branches else J
        out.append({"name": job["name"], "junction": junc, "branches": branches})

    _declutter(out, tips)

    # 事后扫描：不同网共用顶点 = 会短接，宁可报错也不产出这种文件
    owner = {}
    for net in out:
        pts = net.get("path") or [p for b in net.get("branches", []) for p in b["points"]]
        for p in pts:
            t = tuple(p)
            if t in owner and owner[t] != net["name"]:
                raise ValueError(f"网 {owner[t]} 与 {net['name']} 共用顶点 {t}（会短接）")
            owner[t] = net["name"]

    return {"schema_version": "1.0",
            # separate_pins 可能挪过器件 —— 必须把最终坐标返回，
            # 否则调用方拿旧坐标去 build，几何和计划对不上
            "components": [{"ref": c["ref"], "device": c["device"],
                            "value": c.get("value") or c["device"],
                            "x": c["x"], "y": c["y"],
                            "rotation": c.get("rotation", 0)}
                           for c in netlist["components"]],
            "warnings": list(OVERLAP_WARN),
            "nets": out}


def check(plan_doc):
    """自检：正交、都汇到结点、跨网无共线重叠、平行间距"""
    problems, segs = [], []
    for net in plan_doc["nets"]:
        if net.get("junction"):
            for br in net["branches"]:
                pts = br["points"]
                for a, b in zip(pts, pts[1:]):
                    if a[0] != b[0] and a[1] != b[1]:
                        problems.append(f"{net['name']} 斜线段 {a}->{b}")
                    segs.append((net["name"], tuple(a), tuple(b)))
                if tuple(br["points"][-1]) != tuple(net["junction"]):
                    problems.append(f"{net['name']} 支线 {br['pin']} 没汇到结点")
        else:
            pts = net.get("path") or []
            for a, b in zip(pts, pts[1:]):
                if a[0] != b[0] and a[1] != b[1]:
                    problems.append(f"{net['name']} 斜线段 {a}->{b}")
                segs.append((net["name"], tuple(a), tuple(b)))

    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i][0] == segs[j][0]:
                continue
            if _ov(segs[i][1], segs[i][2], segs[j][1], segs[j][2]) > 0:
                problems.append(f"跨网共线重叠 {segs[i][0]}×{segs[j][0]} "
                                f"{segs[i][1]}->{segs[i][2]}")

    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (n1, a1, b1), (n2, a2, b2) = segs[i], segs[j]
            if n1 == n2:
                continue
            for horiz in (True, False):
                s1 = (a1[1] == b1[1]) if horiz else (a1[0] == b1[0])
                s2 = (a2[1] == b2[1]) if horiz else (a2[0] == b2[0])
                if not (s1 and s2):
                    continue
                ax, bx = (1, 0) if horiz else (0, 1)
                if abs(a1[ax] - a2[ax]) >= 2:
                    continue
                lo = max(min(a1[bx], b1[bx]), min(a2[bx], b2[bx]))
                hi = min(max(a1[bx], b1[bx]), max(a2[bx], b2[bx]))
                if hi > lo:
                    problems.append(f"平行间距不足 {n1}×{n2} 仅 "
                                    f"{abs(a1[ax]-a2[ax])} 格")
    return problems
