"""skill 文档一致性测试：skill 里提到的每个工具名，是否真的存在。

文档漂移是这类包最容易出的事 —— 写了 `verify_netdiff` 但工具改了名，
用户照着做就卡住。这个测试把 skill 里的反引号标识符全抽出来，逐个核对：
  · MCP 工具名 → 必须在 server.py 的 TOOLS 里
  · CLI 子命令 → 必须在 cli.py 的 parser 里
  · 模块路径 → 必须能 import
"""
import ast
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

SKILL = os.path.join(HERE, "skill", "SKILL.md")


def mcp_tools():
    sys.path.insert(0, PKG)
    from proteus844 import server
    return {t["name"] for t in server.TOOLS}


def cli_commands():
    src = open(os.path.join(HERE, "cli.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    cmds = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_parser":
            if node.args and isinstance(node.args[0], ast.Constant):
                cmds.add(node.args[0].value)
    return cmds


def defs():
    out = set()
    for root, _, files in os.walk(HERE):
        if "__pycache__" in root or "vendor" in root:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            out |= set(re.findall(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", src))
    return out


def modules():
    out = set()
    for root, _, files in os.walk(HERE):
        if "__pycache__" in root or "vendor" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(root, f), HERE)[:-3]
                out.add(rel.replace(os.sep, "."))
    return out


def main():
    text = open(SKILL, encoding="utf-8").read()
    tokens = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.:/ ,-]{1,40})`", text))
    tools, cmds, mods = mcp_tools(), cli_commands(), modules()
    known_defs = defs()
    known = tools | cmds | mods | known_defs

    # skill 里应该出现、且必须真实存在的关键标识
    # 这些是示例数据/字段名，不要求是工具
    from proteus844 import errors as E
    err_codes = {v for k, v in vars(E.Code).items() if not k.startswith("_")}
    known |= err_codes
    # verify 子模块允许省略包前缀
    known |= {m.split(".")[-1] for m in mods}
    ignore = {
        "RoutePlan", "SW-SPST", "layout_warnings", "terminal_errors",
        "ok:true", "ok:false", "VCC", "GND", "min_len", "threshold",
        "read_image", "Esc", "Ctrl+A", "SW-SPDT", "SW-SPST", "add_terminal", "proteus_place", "proteus_calibrate", "proteus_menu",
        "proteus_save", "proteus_netlist",
        "donor", "pdsprj", "ref", "device", "pins", "nets", "terminals", "x", "y",
        "ground", "power", "input", "output", "bidir", "label", "kind", "name",
        "pin", "value", "rotation", "bbox", "tip_px", "components", "path",
        "junction", "branches", "points", "type", "object", "properties",
        "required", "ROOT.DSN", "ROOT.CDB", "PROJECT.XML", "u1:A", "u1:d",
        "netlist_main.json", "netlist_sub.json", "components.json", "netlist.json",
        "log.md", "out.pdsprj", "segs.json", "juncs.json", "pins.json",
        "boxes.json", "result.json", "图.png", "clp_", "d_",
    }
    suspects = []
    for t in sorted(tokens):
        base = t.split("(")[0].strip()
        ignore_l = {x.lower() for x in ignore}
        if base.lower() in ignore_l or t.lower() in ignore_l:
            continue
        if "." in base and not base.startswith("proteus844"):
            continue
        # 带空格的说明文字跳过
        if " " in base or base.endswith(".py") or base.endswith(".md"):
            continue
        if base in known:
            continue
        if base.startswith("proteus_"):      # GUI 自动化 MCP 的外部工具（proteus_launch 等）
            continue
        if base.startswith("proteus844"):
            try:
                __import__(base)
                continue
            except Exception:
                suspects.append((t, "模块导入失败"))
                continue
        # 形如 U1:A / N1 / 图 1.1 的跳过
        if re.match(r"^[A-Z]+[0-9]", base) or re.match(r"^[A-Za-z]+\d", base):
            continue
        suspects.append((t, "未找到同名工具/命令/模块"))

    print(f"skill 里抽到 {len(tokens)} 个反引号标识符")
    print(f"  MCP 工具 {len(tools)} 个 / CLI 子命令 {len(cmds)} 个 / 模块 {len(mods)} 个")
    if suspects:
        print(f"\n❌ 可疑 {len(suspects)} 个：")
        for t, why in suspects:
            print(f"   `{t}` — {why}")
        return 1
    print("\n✅ skill 里引用的工具全部存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
