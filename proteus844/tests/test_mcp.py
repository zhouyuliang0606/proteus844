"""MCP 服务端冒烟测试：喂几条 JSON-RPC，逐条断言。

要点：
  · 子进程的 cwd 必须是包的上层目录，否则 `-m proteus844.server` 找不到模块
  · 每条响应都要断言，不能只打印（打印型测试永远 exit 0，等于没测）
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                       # ...\proteus844
ROOT = os.path.dirname(PKG)                       # ...（-m 的 cwd）
sys.path.insert(0, ROOT)                          # 从任何目录跑都能 import
DONOR = os.path.join(PKG, "donors", "base.pdsprj")
NETLIST = os.path.join(PKG, "tests", "fig11_netlist.json")

netlist = json.load(open(NETLIST, encoding="utf-8-sig"))

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "donor_info", "arguments": {"donor": DONOR}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "validate_netlist",
                "arguments": {"netlist": netlist, "donor": DONOR}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "plan_route",
                "arguments": {"netlist": netlist, "donor": DONOR}}},
    # 故意给个错的引脚名，必须返回错误码而不是崩
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
     "params": {"name": "validate_netlist",
                "arguments": {"netlist": {"components": [
                    {"ref": "U1:D", "device": "7400", "x": 0, "y": 0}],
                    "nets": [{"name": "X", "pins": [["U1:D", "13"], ["U1:D", "Y"]]}]},
                    "donor": DONOR}}},
]


def main():
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n"
    r = subprocess.run([sys.executable, "-m", "proteus844.server"], cwd=ROOT,
                       input=payload, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    bad = []
    if r.returncode:
        print("子进程失败:", (r.stderr or "")[-300:])
        return 1

    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    if len(lines) != len(REQS):
        bad.append(f"响应条数 {len(lines)} != 请求条数 {len(REQS)}")

    got = {}
    for line in lines:
        resp = json.loads(line)
        got[resp.get("id")] = resp

    if "error" in got.get(1, {}):
        bad.append("initialize 报错")
    n = len(got.get(2, {}).get("result", {}).get("tools", []))
    if n < 15:
        bad.append(f"工具数只有 {n}")
    for rid, name in ((3, "donor_info"), (4, "validate_netlist"), (5, "plan_route")):
        body = json.loads(got[rid]["result"]["content"][0]["text"]) if rid in got else {}
        if not body.get("ok"):
            bad.append(f"{name} 未通过: {body.get('code')}")
    body6 = json.loads(got[6]["result"]["content"][0]["text"]) if 6 in got else {}
    if body6.get("ok") or not body6.get("code"):
        bad.append("错误引脚名没有被拦下（应当返回错误码）")

    print(f"工具 {n} 个；initialize/donor_info/validate/plan 均正常；错引脚返回 {body6.get('code')}")
    if bad:
        for b in bad:
            print("  ❌", b)
        return 1
    print("✅ MCP 冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
