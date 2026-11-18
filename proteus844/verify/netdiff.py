"""第三步（权威验收）：意图网表 vs Proteus 编译出的 SDF 网表，逐网 diff。

用法:
    python netdiff.py netlist.json authoritative.SDF

判定（三态，都可判定）：
    OK        引脚集合完全一致
    SHORT     意图网被并进了更大的网络  —— 真短接
    BROKEN    意图网在 SDF 里被拆成多个 —— 断线

电源网（GND / VCC/VDD）单独处理：意图里挂终端的引脚，只要求出现在对应电源网即可。
"""
import json
import sys
from collections import defaultdict

POWER = {"GND", "VCC/VDD", "VCC", "VDD"}


def parse_sdf(path):
    """返回 (partlist, {net_id: set((ref,pin))})"""
    nets, parts = {}, {}
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")]
    i, mode = 0, None
    while i < len(lines):
        line = lines[i]
        if line.startswith("*PARTLIST"):
            mode = "parts"
        elif line.startswith("*NETLIST"):
            mode = "nets"
        elif line.startswith("*"):
            mode = None
        elif mode == "parts" and line.strip():
            f = line.split(",")
            if len(f) >= 3:
                parts[f[0]] = {"device": f[1], "value": f[2]}
        elif mode == "nets" and line and not line.startswith((" ", "\t")):
            f = [x.strip() for x in line.split(",")]
            # 表头可能是 "名字,数量" 也可能是 "名字,数量,CLASS=POWER"
            if len(f) >= 2 and f[1].isdigit():
                name, count = f[0], int(f[1])
                pins = set()
                for k in range(1, count + 1):
                    pf = [x.strip() for x in lines[i + k].split(",")]
                    if len(pf) >= 3:
                        pins.add((pf[0], pf[2]))     # ref, role, pin
                    elif len(pf) == 2:
                        pins.add((pf[0], pf[1]))     # 电源条目: ref, role
                nets[name] = pins
                i += count
        i += 1
    return parts, nets


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    nj, sdf = sys.argv[1], sys.argv[2]

    spec = json.load(open(nj, encoding="utf-8"))
    parts, sdf_nets = parse_sdf(sdf)

    print(f"意图网表: {len(spec.get('components', []))} 器件 / {len(spec.get('nets', []))} 网")
    print(f"Proteus : {len(parts)} 器件 / {len(sdf_nets)} 网（含电源网）\n")

    ok = short = broken = 0
    lines = []

    for net in spec.get("nets", []):
        want = {(r, p) for r, p in net.get("pins", [])}
        name = net.get("name", "?")
        if len(want) < 2:
            continue                       # 单脚网（如裸 GND 终端）单独看
        exact = [n for n, pins in sdf_nets.items() if pins == want]
        if exact:
            ok += 1
            lines.append(f"  OK      {name:14} {sorted(want)}")
            continue
        superset = [n for n, pins in sdf_nets.items()
                    if n not in POWER and want < pins]
        subset = [n for n, pins in sdf_nets.items()
                  if n not in POWER and want & pins and not (want <= pins)]
        if superset:
            short += 1
            n = superset[0]
            lines.append(f"  SHORT   {name:14} 被并入 {n}（多出 {sorted(sdf_nets[n] - want)}）")
        elif subset:
            broken += 1
            got = sorted({p for n in subset for p in sdf_nets[n] & want})
            lines.append(f"  BROKEN  {name:14} 被拆成 {subset}（只找到 {got}）")
        else:
            broken += 1
            lines.append(f"  MISSING {name:14} SDF 里找不到 {sorted(want)}")

    print("=== 信号网逐网比对 ===")
    for l in lines:
        print(l)

    # 电源部分：意图里挂终端的引脚是否落在对应电源网
    print("\n=== 电源网 ===")
    for t in spec.get("terminals", []):
        pin = tuple(t.get("pin", []))
        kind = t.get("kind", "")
        target = "GND" if kind == "ground" else "VCC/VDD"
        hit = pin in sdf_nets.get(target, set())
        print(f"  {kind:7} {pin}  ->  {'在 ' + target if hit else '⚠ 不在 ' + target}")

    total = ok + short + broken
    print(f"\n合计 {total} 个信号网：OK {ok} / SHORT {short} / BROKEN+MISSING {broken}")
    print("判定：", "✅ 电气一致" if total and short == 0 and broken == 0
          else "❌ 与意图不符，见上面逐条")
    return 0 if total and short == 0 and broken == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
