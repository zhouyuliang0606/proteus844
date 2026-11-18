"""一键自检：把整个包跑一遍，给出一张体检表。

    python -m proteus844.selftest          # 全部
    python -m proteus844.selftest --fast   # 跳过慢的（端到端/拓扑）

每项都子进程跑，互不污染；失败不中断，最后统一汇报并给退出码。
"""
import importlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

CHECKS = [
    # (分组, 名字, 模块, 是否慢)
    ("接口", "MCP 工具清单", "proteus844.tests.test_mcp", False),
    ("接口", "CLI 子命令", "__cli__", False),
    ("文档", "README / skill 就位", "__docs__", False),
    ("文档", "skill 引用一致性", "proteus844.tests.test_skill_docs", False),
    ("链路", "端到端 8 步", "proteus844.tests.test_e2e", True),
    ("链路", "拓扑自动布局", "proteus844.tests.test_topology", True),
    ("识别", "建网 trace", "proteus844.tests.test_trace", False),
    ("识别", "引脚提示图", "proteus844.tests.test_pin_hints", True),
    ("识别", "对着图初筛", "proteus844.tests.test_against_image", True),
    ("回归", "总回归 13 项", "proteus844.tests.regression", True),
]


def _run(mod):
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", mod], cwd=PKG, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, time.time() - t0, (r.stdout or r.stderr or "").strip()


def _cli():
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "proteus844.cli", "--help"], cwd=PKG,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    n = sum(1 for c in ("seg", "junc", "pins", "trace", "build", "verify", "init",
                        "assemble", "draw", "verify-file", "donor-add", "hints", "donors")
            if c in r.stdout)
    return r.returncode == 0 and n >= 13, time.time() - t0, f"{n} 个子命令"


def _docs():
    t0 = time.time()
    need = ("README.md", os.path.join("skill", "SKILL.md"),
            os.path.join("experiments", "README.md"))
    miss = [f for f in need if not os.path.exists(os.path.join(HERE, f))]
    return not miss, time.time() - t0, ("文档齐全" if not miss else f"缺 {miss}")


def _env():
    info = {"python": sys.version.split()[0], "cwd": PKG}
    for m in ("numpy", "PIL"):
        try:
            importlib.import_module(m)
            info[m] = "ok"
        except Exception:
            info[m] = "缺失"
    info["donors"] = len([f for f in os.listdir(os.path.join(HERE, "donors"))
                          if f.endswith(".pdsprj")])
    return info


def main(argv):
    fast = "--fast" in argv
    print("=== proteus844 自检 ===")
    env = _env()
    print(f"Python {env['python']}   numpy {env['numpy']}   Pillow {env['PIL']}"
          f"   donor {env['donors']} 个\n")

    rows, bad = [], 0
    group = None
    for g, name, mod, slow in CHECKS:
        if fast and slow:
            rows.append((g, name, None, 0.0, "跳过（--fast）"))
            continue
        if g != group:
            print(f"[{g}]")
            group = g
        if mod == "__cli__":
            ok, dt, tail = _cli()
        elif mod == "__docs__":
            ok, dt, tail = _docs()
        else:
            ok, dt, tail = _run(mod)
        last = tail.splitlines()[-1].strip() if tail else ""
        rows.append((g, name, ok, dt, last[:56]))
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} {name:<16} {dt:5.1f}s  {last[:56]}")

    total = len([r for r in rows if r[2] is not None])
    print(f"\n{total - bad}/{total} 通过" + ("  ✅ 全部正常" if bad == 0 else f"  ❌ {bad} 项失败"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
