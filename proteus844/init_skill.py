"""`proteus844 init` —— 把 skill 装到用户机器上，并打印 MCP 配置片段。"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_SRC = os.path.join(HERE, "skill", "SKILL.md")


def default_skill_dirs():
    home = os.path.expanduser("~")
    return [os.path.join(home, ".workbuddy", "skills"),
            os.path.join(home, ".claude", "skills"),
            os.path.join(home, ".dsh", "skills")]


def install(skill_dir=None, name="proteus844", force=False):
    if skill_dir is None:
        for cand in default_skill_dirs():
            if os.path.isdir(os.path.dirname(cand)) or os.path.isdir(cand):
                skill_dir = cand
                break
        else:
            skill_dir = default_skill_dirs()[0]
    dest = os.path.join(skill_dir, name)
    if os.path.exists(dest) and not force:
        return {"ok": False, "path": dest, "message": "目标已存在，加 --force 覆盖"}
    os.makedirs(dest, exist_ok=True)
    shutil.copy2(SKILL_SRC, os.path.join(dest, "SKILL.md"))

    # 附带参考资料（若包里有）
    ref_src = os.path.join(HERE, "skill", "references")
    if os.path.isdir(ref_src):
        shutil.copytree(ref_src, os.path.join(dest, "references"), dirs_exist_ok=True)
    return {"ok": True, "path": dest}


def mcp_snippet():
    server = os.path.join(HERE, "server.py")
    py = sys.executable
    return {
        "mcpServers": {
            "proteus844": {
                "command": py,
                "args": ["-m", "proteus844.server"],
                "cwd": os.path.dirname(HERE),
            }
        }
    }


def report(skill_dir=None, force=False):
    r = install(skill_dir, force=force)
    lines = []
    if r["ok"]:
        lines.append(f"✅ skill 已装到: {r['path']}")
    else:
        lines.append(f"⚠ {r['message']}: {r['path']}")
    donors = os.path.join(HERE, "donors")
    names = sorted(os.listdir(donors)) if os.path.isdir(donors) else []
    lines.append(f"📦 内置供体 ({len(names)}): {', '.join(names)}")
    lines.append("\n把下面这段加进你的 MCP 客户端配置：\n")
    lines.append(json.dumps(mcp_snippet(), indent=2, ensure_ascii=False))
    lines.append("\n先跑一次自检：")
    lines.append(f"  {sys.executable} -m proteus844.cli donors")
    lines.append(f"  {sys.executable} -m proteus844.cli verify "
                 f"{os.path.join(donors, names[0]) if names else '<donor>'}")
    return "\n".join(lines)
