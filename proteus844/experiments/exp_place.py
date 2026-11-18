"""自动布局测试：只给拓扑（器件 + 网表，无坐标），看能不能一路画成合格工程。

⚠ 这是**负面实验记录**，不是通过的测试：结论是这条路走不通，
数字留档供以后参考。修改后请保持 exit 0。

这测的是"AI 只负责认、工具负责摆"这条路。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844.build import writer
from proteus844.route import place as PL
from proteus844.route import plan as RP
from proteus844.verify import file_netlist as F

DONORS = os.path.join(HERE, "donors")
TESTS = os.path.join(HERE, "tests")


def strip_coords(netlist):
    """只留拓扑：ref / device / value，去掉 x,y,pins"""
    return {"components": [{"ref": c["ref"], "device": c["device"],
                            "value": c.get("value") or c["device"]}
                           for c in netlist["components"]],
            "nets": netlist.get("nets", []),
            "terminals": netlist.get("terminals", [])}


def run(tag, netlist, donor):
    bare = strip_coords(netlist)
    placed = PL.place(bare, donor)
    xs = [c["x"] for c in placed["components"]]
    ys = [c["y"] for c in placed["components"]]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    print(f"\n[{tag}] {len(placed['components'])} 器件 / {len(placed['nets'])} 网"
          f" → 布局 {w}×{h} 格")
    try:
        doc = RP.plan(placed, donor)
    except ValueError as exc:
        print(f"[{tag}] ❌ 规划失败: {exc}")
        return False
    probs = RP.check(doc)
    hard = [p for p in probs if "平行间距" not in p and "共线重叠" not in p]
    ovl = len([p for p in probs if "共线重叠" in p])
    out = os.path.join(tempfile.gettempdir(), f"place_{tag}.pdsprj")
    writer.build(placed, doc, donor, out)
    d = F.diff(bare, out)
    print(f"[{tag}] 硬问题 {len(hard)} / 共线重叠 {ovl} / 验收 {d['summary']}"
          f" / 端子 {d.get('terminals', {}).get('checked', 0)} 个")
    return d["ok"] and not hard


def main():
    try:
        return _main()
    except Exception as exc:      # 负面实验：崩溃也要记下来并正常退出
        print(f"  （记录）失败：{type(exc).__name__}: {exc}")
        return 0


def _main():
    ok = 0
    total = 0
    # 图 1.1
    nl = json.load(open(os.path.join(TESTS, "fig11_netlist.json"), encoding="utf-8-sig"))
    total += 1
    ok += run("fig11", nl, os.path.join(DONORS, "base.pdsprj"))
    # 编码器
    enc = json.load(open(os.path.join(TESTS, "encoder_netlist.json"), encoding="utf-8-sig"))
    signal = {"components": [c for c in
                             json.load(open(os.path.join(TESTS, "encoder_components.json"),
                                            encoding="utf-8-sig"))],
              "nets": enc["nets"], "terminals": enc.get("terminals", [])}
    total += 1
    ok += run("encoder", signal, os.path.join(DONORS, "kit.pdsprj"))
    print(f"\n{ok}/{total} 个电路能只凭拓扑自动布局并画出合格工程")
    return 0


if __name__ == "__main__":
    sys.exit(main())
