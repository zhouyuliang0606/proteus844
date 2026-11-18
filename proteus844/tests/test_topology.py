"""只给拓扑，能不能一路画成合格工程 —— CAD 式分工的验收。

输入只有 ref / device / value 和「谁连谁」，**没有任何坐标**。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(HERE))

from proteus844 import pipeline

DONORS = os.path.join(HERE, "donors")
TESTS = os.path.join(HERE, "tests")


def topology_only(netlist):
    return {"components": [{"ref": c["ref"], "device": c["device"],
                            "value": c.get("value") or c["device"]}
                           for c in netlist["components"]],
            "nets": netlist.get("nets", []),
            "terminals": []}


def run(tag, topo, donor):
    out = os.path.join(os.environ.get("TEMP", "."), f"topo_{tag}.pdsprj")
    res = pipeline.build_from_topology(topo, donor, out, verbose=False)
    if res["ok"]:
        print(f"✅ {tag}: 布局 {res['layout'][0]}×{res['layout'][1]} 格，"
              f"间距 {res['gaps']}，验收 {res['verify']['summary']}")
        return True
    print(f"❌ {tag}: {res.get('error')}")
    return False


def main():
    ok = total = 0

    nl = json.load(open(os.path.join(TESTS, "fig11_netlist.json"), encoding="utf-8-sig"))
    total += 1
    ok += run("fig11", topology_only(nl), os.path.join(DONORS, "base.pdsprj"))

    enc_nets = json.load(open(os.path.join(TESTS, "encoder_netlist.json"), encoding="utf-8-sig"))
    comps = json.load(open(os.path.join(TESTS, "encoder_components.json"), encoding="utf-8-sig"))
    enc_topo = {"components": [{"ref": c["ref"], "device": c["device"],
                                "value": c.get("value") or c["device"]} for c in comps],
                "nets": enc_nets["nets"], "terminals": []}
    total += 1
    ok += run("encoder", enc_topo, os.path.join(DONORS, "kit.pdsprj"))

    print(f"\n{ok}/{total} 个电路，只凭拓扑就画出了合格工程")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
