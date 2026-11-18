"""一键回归：不依赖 Proteus GUI 的全部检查。

每轮改完都跑一遍：
    python -m proteus844.tests.regression
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # proteus844/
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

DONORS = os.path.join(HERE, "donors")
TESTS = os.path.join(HERE, "tests")
BASE = os.path.join(DONORS, "base.pdsprj")
KIT = os.path.join(DONORS, "kit.pdsprj")

results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:                                   # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}: {detail}")


def t_donor():
    from proteus844.verify import donor_check as D
    r = D.check(BASE)
    return r["components"] >= 1, f"{r['components']} 器件 / {r['wires']} 导线"


def t_symbol():
    from proteus844.route import plan as P
    pins = P._symbol_pins(BASE, "7400")
    return set(pins) == {"A", "B", "Y"}, f"7400 引脚 {sorted(pins)}"


def t_plan_fig11():
    from proteus844.route import plan as P
    nl = json.load(open(os.path.join(TESTS, "fig11_netlist.json"), encoding="utf-8-sig"))
    doc = P.plan(nl, BASE)
    probs = [p for p in P.check(doc) if "平行间距" not in p]
    return not probs, f"{len(doc['nets'])} 网，硬问题 {len(probs)}"


def t_build_fig11():
    from proteus844 import pipeline
    from proteus844.verify import file_netlist as F
    comps = [
        {"ref": "LS1", "device": "LOGICSTATE", "pins": {"Q0": [56, 52.5]}, "bbox": [34, 44, 50, 61]},
        {"ref": "LS2", "device": "LOGICSTATE", "pins": {"Q0": [54, 125]}, "bbox": [34, 116, 48, 134]},
        {"ref": "LS3", "device": "LOGICSTATE", "pins": {"Q0": [56, 205]}, "bbox": [36, 197, 50, 214]},
        {"ref": "U1:D", "device": "7400", "pins": {"A": [149, 52.5], "B": [149, 69.5], "Y": [204, 60.5]},
         "bbox": [149, 44, 187, 78]},
        {"ref": "U3:A", "device": "7400", "pins": {"A": [154, 125], "B": [154, 141.5], "Y": [210, 134]},
         "bbox": [154, 116, 194, 150]},
        {"ref": "U3:B", "device": "7400", "pins": {"A": [159, 205], "B": [159, 222], "Y": [215, 213.5]},
         "bbox": [159, 197, 199, 231]},
        {"ref": "U4:A", "device": "7410",
         "pins": {"A": [274, 126], "B": [274, 134], "C": [274, 142.5], "Y": [330, 134.5]},
         "bbox": [274, 117, 314, 151]},
        {"ref": "R14", "device": "RES", "value": "100", "rotation": 270,
         "pins": {"1": [363.5, 151], "2": [363.5, 175]}, "bbox": [356, 149, 371, 177]},
        {"ref": "D2", "device": "LED-RED", "pins": {"A": [363.5, 195], "K": [363.5, 200]},
         "bbox": [350, 188, 378, 226]},
    ]
    nl = json.load(open(os.path.join(TESTS, "fig11_netlist.json"), encoding="utf-8-sig"))
    out = os.path.join(tempfile.gettempdir(), "reg_fig11.pdsprj")
    res = pipeline.assemble(comps, nl["nets"], out, BASE, 8.5, verbose=False)
    if not res.get("ok"):
        return False, f"stage={res.get('stage')}"
    d = F.diff(nl, out)
    return d["ok"], f"{d['summary']} 布局 {res['verify']['rebuilt_nets']} 网"


def t_build_encoder():
    from proteus844 import pipeline
    from proteus844.verify import file_netlist as F
    comps = json.load(open(os.path.join(TESTS, "encoder_components.json"), encoding="utf-8-sig"))
    nets = json.load(open(os.path.join(TESTS, "encoder_netlist.json"), encoding="utf-8-sig"))["nets"]
    out = os.path.join(tempfile.gettempdir(), "reg_enc.pdsprj")
    res = pipeline.assemble(comps, nets, out, KIT, pipeline.estimate_ppg(comps, KIT), verbose=False)
    if not res.get("ok"):
        return False, f"stage={res.get('stage')}"
    xs = [c["x"] for c in res["netlist"]["components"]]
    ys = [c["y"] for c in res["netlist"]["components"]]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    d = F.diff({"nets": [n for n in nets if n["name"].upper() not in ("GND", "VCC")]}, out)
    return d["ok"] and w <= 140 and h <= 70, f"{d['summary']} 布局 {w}x{h}（A4=132x70，20+ 器件要 A3）"


def t_order_rule():
    """导线方向规则：同一条路径对调首尾，写出的文件必须一致"""
    from proteus844.build import writer as W
    comps = [{"ref": "U7", "device": "7448", "value": "7448", "x": 10, "y": 24, "rotation": 0},
             {"ref": "R0", "device": "RES", "value": "200", "x": 32, "y": 40, "rotation": 0}]
    nl = {"components": comps, "nets": [], "terminals": []}
    from proteus844.route import plan as P
    tips = P.pin_table(nl, KIT)
    qa = [int(v) for v in tips[("U7", "QA")][:2]]
    r0 = [int(v) for v in tips[("R0", "1")][:2]]
    path = [[r0[0], r0[1]], [r0[0] - 1, r0[1]], [qa[0] + 5, r0[1]],
            [qa[0] + 5, qa[1]], [qa[0] + 1, qa[1]], [qa[0], qa[1]]]
    a = os.path.join(tempfile.gettempdir(), "reg_ord_a.pdsprj")
    b = os.path.join(tempfile.gettempdir(), "reg_ord_b.pdsprj")
    pins = [["R0", "1"], ["U7", "QA"]]
    W.build(nl | {"nets": [{"name": "N0", "pins": pins}]},
            {"nets": [{"name": "N0", "junction": None, "pins": pins, "path": path}]}, KIT, a)
    pins2 = [["U7", "QA"], ["R0", "1"]]
    W.build(nl | {"nets": [{"name": "N0", "pins": pins2}]},
            {"nets": [{"name": "N0", "junction": None, "pins": pins2,
                       "path": list(reversed(path))}]}, KIT, b)
    from proteus844.verify import file_netlist as F
    wa = F.reader.load(a)
    wb = F.reader.load(b)
    return wa == wb, "两种写法产出字节相同" if wa == wb else "两种写法产出不同（规则未生效）"


def t_compare_tool():
    from proteus844.verify import compare_netlists as C
    nets = json.load(open(os.path.join(TESTS, "encoder_netlist.json"), encoding="utf-8-sig"))["nets"]
    same = C.compare(nets, nets)
    import copy
    bad = copy.deepcopy(nets)
    bad[0] = {"name": bad[0]["name"], "pins": bad[0]["pins"][:-1]}
    diff = C.compare(nets, bad)
    return same["ok"] and not diff["ok"], f"自比 {same['ok']} / 改坏 {diff['ok']}"


def t_mcp():
    reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    payload = "\n".join(json.dumps(r) for r in reqs) + "\n"
    r = subprocess.run([sys.executable, "-m", "proteus844.server"], input=payload,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    lines = [json.loads(x) for x in r.stdout.strip().splitlines()]
    tools = lines[1]["result"]["tools"]
    return len(tools) >= 14, f"{len(tools)} 个工具"


def t_pin_hints():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.tests.test_pin_hints"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    cov = [l for l in r.stdout.splitlines() if l.startswith("覆盖")]
    return r.returncode == 0, (cov[0] if cov else "失败")


def t_against_image():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.tests.test_against_image"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    n = r.stdout.count("✅ 抓到")
    m = [l for l in r.stdout.splitlines() if l.startswith("基线")]
    return r.returncode == 0, f"反样本 {n}/3 抓到；{m[-1][3:].strip() if m else ''}"


def t_topology():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.tests.test_topology"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    detail = lines[-1].strip() if lines else (r.stderr[-120:] or "无输出")
    return r.returncode == 0, detail


def t_skill_docs():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.tests.test_skill_docs"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    return r.returncode == 0, "skill 引用的工具全部存在" if r.returncode == 0 else "有失效引用"


def t_e2e():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.tests.test_e2e"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    last = [l for l in r.stdout.strip().splitlines() if "通过" in l]
    return r.returncode == 0, (last[-1].strip() if last else "失败")
 

def main():
    print("=== proteus844 回归 ===")
    for name, fn in (("donor 体检", t_donor), ("符号引脚", t_symbol),
                     ("plan_route(图1.1)", t_plan_fig11), ("build(图1.1)", t_build_fig11),
                     ("build(编码器)", t_build_encoder), ("导线方向规则", t_order_rule),
                     ("双路比对工具", t_compare_tool), ("MCP 服务", t_mcp),
                     ("skill 文档一致性", t_skill_docs), ("端到端链路", t_e2e),
                     ("拓扑自动布局", t_topology), ("对着图初筛", t_against_image),
                     ("引脚提示图", t_pin_hints)):
        check(name, fn)
    bad = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results)-len(bad)}/{len(results)} 通过"
          + (f"，失败：{bad}" if bad else " ✅ 全绿"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
