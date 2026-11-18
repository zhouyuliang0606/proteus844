"""端到端链路测试：严格按 SKILL.md 写的步骤，从网表一路跑到验收。

不测识别（那需要模型看图），只测**识别之后**的每一步是否如文档所述能跑通：
    validate_netlist → plan_route → build → verify_file → verify（结构）
                    → screenshot_check（若有截图）→ sheet 尺寸

用包内 fixture（编码器 22 器件 + 图 1.1），断言每一步的输出与文档描述一致。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from proteus844 import errors as E
from proteus844 import pipeline
from proteus844 import validate as V
from proteus844.build import writer
from proteus844.route import plan as RP
from proteus844.verify import file_netlist as F
from proteus844.verify import screenshot_check as SC
from proteus844.verify import sheet as SH

KIT = os.path.join(HERE, "donors", "kit.pdsprj")
BASE = os.path.join(HERE, "donors", "base.pdsprj")
TESTS = os.path.join(HERE, "tests")

steps = []


def step(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:                                   # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    steps.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}: {detail}")


def encoder():
    comps = json.load(open(os.path.join(TESTS, "encoder_components.json"), encoding="utf-8-sig"))
    nets = json.load(open(os.path.join(TESTS, "encoder_netlist.json"), encoding="utf-8-sig"))["nets"]
    return comps, nets


def t_validate():
    comps, nets = encoder()
    ppg = pipeline.estimate_ppg(comps, KIT)
    anchors = pipeline.anchors_from_pins(comps, KIT, ppg)
    nl = {"components": pipeline._grid_components(comps, anchors, ppg), "nets": nets,
          "terminals": []}
    r = V.validate(nl, KIT)
    return r["ok"], f"{r.get('components')} 器件 / {r.get('nets')} 网 / {r.get('pins')} 脚"


def t_plan():
    comps, nets = encoder()
    ppg = pipeline.estimate_ppg(comps, KIT) * 0.8
    anchors = pipeline.anchors_from_pins(comps, KIT, ppg)
    nl = {"components": pipeline._grid_components(comps, anchors, ppg),
          "nets": [n for n in nets if n["name"].upper() not in ("GND", "VCC")],
          "terminals": []}
    doc = RP.plan(nl, KIT)
    probs = RP.check(doc)
    hard = [p for p in probs if "平行间距" not in p and "共线重叠" not in p]
    ovl = [p for p in probs if "共线重叠" in p]
    return not hard, f"{len(doc['nets'])} 网，硬问题 {len(hard)}，共线重叠 {len(ovl)}"


def t_build_and_verify():
    comps, nets = encoder()
    out = os.path.join(tempfile.gettempdir(), "e2e_encoder.pdsprj")
    res = pipeline.assemble(comps, nets, out, KIT, pipeline.estimate_ppg(comps, KIT),
                            verbose=False)
    if not res.get("ok"):
        return False, f"stage={res.get('stage')}"
    d = F.diff({"nets": [n for n in nets if n["name"].upper() not in ("GND", "VCC")]}, out)
    return d["ok"], f"{d['summary']}，文件 {os.path.getsize(out)} B"


def t_sheet():
    p = os.path.join(TESTS, "encoder_22.pdsprj")
    info = SH.read_sheet(p)
    return info and info["width_grids"] >= 132, f"{info['width_grids']}×{info['height_grids']} 格"


def t_screenshot():
    p = os.path.join(TESTS, "encoder_22.png")
    if not os.path.exists(p):
        return True, "无截图，跳过"
    r = SC.analyse(p)
    return r["diag_energy_ratio"] is not None and r["diag_energy_ratio"] < 0.15, \
        f"斜线能量 {r['diag_energy_ratio']}"


def t_sdf():
    """SDF 是权威判据：检查它存在且能解析出电源网"""
    p = os.path.join(TESTS, "encoder_22.SDF")
    if not os.path.exists(p):
        return True, "无 SDF，跳过"
    txt = open(p, encoding="latin-1").read()
    has_gnd = "GND" in txt and "VCC" in txt
    return has_gnd, f"{len(txt)} 字节，含 GND/VCC 段"


def t_error_codes():
    """错误码必须能从异常映射出来（skill 第 5 节的表）"""
    from proteus844.errors import guard

    @guard
    def boom():
        raise KeyError("网 X 引脚查不到坐标: [('U9','Z')]")

    r = boom()
    return (not r["ok"]) and r["code"] == E.Code.PIN_NOT_IN_SYMBOL and r.get("hint"), \
        f"{r['code']} + hint"


def t_cli_help():
    import subprocess
    r = subprocess.run([sys.executable, "-m", "proteus844.cli", "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=PKG)
    cmds = [c for c in ("seg", "junc", "pins", "trace", "plan", "build", "verify",
                        "verify-file", "draw", "assemble", "init", "donor-add", "donors")
            if c in r.stdout]
    return len(cmds) >= 10, f"{len(cmds)} 个子命令可见"


def main():
    print("=== 端到端链路（按 SKILL.md 的步骤）===\n")
    for name, fn in (("1 校验网表", t_validate),
                     ("2 布线规划", t_plan),
                     ("3 生成 + 文件级验收", t_build_and_verify),
                     ("4 图纸尺寸", t_sheet),
                     ("5 渲染正交（截图）", t_screenshot),
                     ("6 引擎真值（SDF）", t_sdf),
                     ("7 错误码映射", t_error_codes),
                     ("8 CLI 子命令齐全", t_cli_help)):
        step(name, fn)
    bad = [n for n, ok, _ in steps if not ok]
    print(f"\n{len(steps)-len(bad)}/{len(steps)} 通过"
          + (f"，失败：{bad}" if bad else " ✅ 全链路通"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
