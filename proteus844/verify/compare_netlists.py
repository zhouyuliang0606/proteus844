"""双路识别比对：两份网表按「网络的引脚集合」对齐，只报差异。

用法：
    python -m proteus844.verify.compare_netlists main.json sub.json
    # 或作函数：compare(a_nets, b_nets)
"""
import json
import sys


def _key(net):
    return frozenset(tuple(p) for p in net["pins"])


def compare(a_nets, b_nets, name_a="主路", name_b="副路"):
    A = {_key(n): n.get("name", "?") for n in a_nets}
    B = {_key(n): n.get("name", "?") for n in b_nets}
    only_a = [{"net": A[k], "pins": sorted(k)} for k in A.keys() - B.keys()]
    only_b = [{"net": B[k], "pins": sorted(k)} for k in B.keys() - A.keys()]

    # 有交叠但分组不同：同一个引脚出现在两边的不同网络里
    pin_a = {}
    for k, nm in A.items():
        for p in k:
            pin_a[p] = nm
    split = []
    for k, nm in B.items():
        groups = {pin_a[p] for p in k if p in pin_a}
        if len(groups) > 1:
            split.append({"副路网": nm, "引脚": sorted(k), "主路对应多个网": sorted(groups)})
        elif groups and nm not in groups and any(p in pin_a for p in k):
            pass

    agree = len(A.keys() & B.keys())
    return {
        "agree": agree,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "split_disagreements": split,
        "ok": not only_a and not only_b and not split,
        "note": f"{name_a} {len(A)} 网 / {name_b} {len(B)} 网 / 一致 {agree} 网",
    }


def main():
    a = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    b = json.load(open(sys.argv[2], encoding="utf-8-sig"))
    a = a["nets"] if isinstance(a, dict) else a
    b = b["nets"] if isinstance(b, dict) else b
    r = compare(a, b)
    print(r["note"])
    for x in r["only_in_a"]:
        print("  只在主路:", x["net"], x["pins"])
    for x in r["only_in_b"]:
        print("  只在副路:", x["net"], x["pins"])
    for x in r["split_disagreements"]:
        print("  分组冲突:", x["副路网"], x["引脚"], "主路拆成了", x["主路对应多个网"])
    print("判定:", "✅ 两路一致" if r["ok"] else "⚠ 有差异，回图核对")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
