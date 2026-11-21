"""proteus844 MCP 服务端（stdio JSON-RPC 2.0，无第三方依赖）。

启动：python -m proteus844.server
协议：每行一条 JSON-RPC 消息；stdin 读请求，stdout 写响应。

工具（9 个）：
  donor_info / symbol_table / recognize_segments / recognize_junctions
  validate_netlist / plan_route / build / verify_structural / verify_netdiff
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
VENDOR = os.path.join(HERE, "vendor", "ref844")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

from proteus844 import errors as E                       # noqa: E402

VERSION = "0.2.0"

TOOLS = [
    {"name": "donor_info", "description": "列出供体工程里的器件、引脚名与包。一切的前提。",
     "inputSchema": {"type": "object", "required": ["donor"],
                     "properties": {"donor": {"type": "string"}}}},
    {"name": "symbol_table", "description": "导出符号尺寸表（引脚尖坐标/包围盒/推荐标尺）。",
     "inputSchema": {"type": "object", "required": ["donor"],
                     "properties": {"donor": {"type": "string"}}}},
    {"name": "recognize_segments", "description": "图片 → 横竖线段（像素坐标）。",
     "inputSchema": {"type": "object", "required": ["image"],
                     "properties": {"image": {"type": "string"},
                                    "min_len": {"type": "integer", "default": 12},
                                    "threshold": {"type": "integer", "default": 140}}}},
    {"name": "recognize_junctions", "description": "图片 → 实心结点（带 EDT 峰值）。",
     "inputSchema": {"type": "object", "required": ["image"],
                     "properties": {"image": {"type": "string"},
                                    "peak": {"type": "number", "default": 2.0}}}},
    {"name": "validate_netlist", "description": "生成前校验网表：引脚名/位号/器件是否可用。",
     "inputSchema": {"type": "object", "required": ["netlist", "donor"],
                     "properties": {"netlist": {"type": "object"},
                                    "donor": {"type": "string"}}}},
    {"name": "plan_route", "description": "算布线方案：通道分配 + 星形结点 + 两脚折线。",
     "inputSchema": {"type": "object", "required": ["netlist", "donor"],
                     "properties": {"netlist": {"type": "object"},
                                    "donor": {"type": "string"},
                                    "min_spacing": {"type": "integer", "default": 2}}}},
    {"name": "build", "description": "按网表(+可选布线方案)写出 .pdsprj。",
     "inputSchema": {"type": "object", "required": ["netlist", "out", "donor"],
                     "properties": {"netlist": {"type": "object"},
                                    "plan": {"type": "object"},
                                    "donor": {"type": "string"},
                                    "out": {"type": "string"}}}},
    {"name": "trace", "description": "线段+结点+引脚尖 → 网络表（几何建网，靠端点不靠相交）。",
     "inputSchema": {"type": "object",
                     "required": ["segments", "pins"],
                     "properties": {
                         "segments": {"type": "array", "description": "[{a:[x,y],b:[x,y]}]"},
                         "junctions": {"type": "array", "description": "[{x,y}]"},
                         "pins": {"type": "array", "description": "[{ref,pin,tip:[x,y]}]"},
                         "boxes": {"type": "array", "description": "器件本体包围盒 [[x0,y0,x1,y1]]"},
                         "tol": {"type": "number", "default": 2.5}}}},
    {"name": "probe_project",
     "description": "探测 .pdsprj 的 Proteus 版本（RELEASE/FILEVER/CDB）并判断本工具是否支持。",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}}, "required": ["project"]}},
    {"name": "review_layout",
     "description": "体检画图美观度：是否居中、是否装得下、绕线系数、跨网共线。返回 0~100 观感分。",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"},
         "donor": {"type": "string"}}, "required": ["project"]}},
    {"name": "check_overlap", "description": "查共线重叠（含网络归属）。只作可读性提示，不是对错判据。",
     "inputSchema": {"type": "object", "required": ["project"],
                     "properties": {"project": {"type": "string"}}}},
    {"name": "verify_recognition",
     "description": "逐引脚比对出线方向（图 vs 画）。能抓 rotation/朝向错，netdiff 抓不到。",
     "inputSchema": {"type": "object",
                     "required": ["image", "project", "netlist", "components",
                                  "donor", "px_per_grid"],
                     "properties": {"image": {"type": "string"},
                                    "project": {"type": "string"},
                                    "netlist": {"type": "object"},
                                    "components": {"type": "array"},
                                    "donor": {"type": "string"},
                                    "px_per_grid": {"type": "number"}}}},
    {"name": "pin_hints",
     "description": "把一个器件放大标注，列出候选端点编号+坐标，让 AI 读编号而不是量像素",
     "inputSchema": {"type": "object", "required": ["image", "bbox", "out_png"],
                     "properties": {"image": {"type": "string"},
                                    "bbox": {"type": "array", "items": {"type": "number"}},
                                    "out_png": {"type": "string"},
                                    "scale": {"type": "integer", "default": 8},
                                    "min_len": {"type": "integer", "default": 3},
                                    "max_points": {"type": "integer", "default": 80}}}},
    {"name": "check_against_image",
     "description": "对着图初筛网表：哪些网可能没接上/接错（会误报，只作复核提示）",
     "inputSchema": {"type": "object", "required": ["components", "netlist", "image"],
                     "properties": {"components": {"type": "array"},
                                    "netlist": {"type": "array"},
                                    "image": {"type": "string"},
                                    "threshold": {"type": "integer", "default": 140},
                                    "min_len": {"type": "integer", "default": 6}}}},
    {"name": "build_topology",
     "description": "只给拓扑（器件+网表，无坐标）→ 自动布局+布线+写盘+验收。",
     "inputSchema": {"type": "object", "required": ["netlist", "donor", "out"],
                     "properties": {"netlist": {"type": "object",
                                                "description": "components 只需 ref/device/value"},
                                    "donor": {"type": "string"},
                                    "out": {"type": "string"}}}},
    {"name": "verify_file", "description": "从 .pdsprj 文件本身重建网络并 diff（不需要 Proteus）。",
     "inputSchema": {"type": "object", "required": ["netlist", "project"],
                     "properties": {"netlist": {"type": "object"},
                                    "project": {"type": "string"}}}},
    {"name": "draw", "description": "一键：图片+器件清单 → .pdsprj，含布线、生成、验收。",
     "inputSchema": {"type": "object",
                     "required": ["image", "out", "donor", "components", "px_per_grid"],
                     "properties": {"image": {"type": "string"},
                                    "out": {"type": "string"},
                                    "donor": {"type": "string"},
                                    "components": {"type": "array"},
                                    "px_per_grid": {"type": "number"},
                                    "tol": {"type": "number", "default": 2.5}}}},
    {"name": "verify_structural", "description": "读回 .pdsprj，列器件与坐标（不依赖 Proteus）。",
     "inputSchema": {"type": "object", "required": ["project"],
                     "properties": {"project": {"type": "string"}}}},
    {"name": "verify_netdiff", "description": "意图网表 vs Proteus 编译出的 SDF，逐网 diff。",
     "inputSchema": {"type": "object", "required": ["netlist", "sdf"],
                     "properties": {"netlist": {"type": "object"},
                                    "sdf": {"type": "string"}}}},
]


# ---------------- 具体实现 ----------------

def _donor_info(args):
    from proteus844.route import plan as P
    from proteus844.build import writer  # noqa: F401  先把 vendor 挂进 sys.path
    donor = args["donor"]
    from component_codec import Circuit
    c = Circuit(donor)
    out = {}
    for dev in sorted(c.templates):
        pins = P._symbol_pins(donor, dev)
        out[dev] = {name: {"offset": [v[0], v[1]], "dir": [v[2], v[3]]}
                    for name, v in pins.items()}
    return E.ok(donor=donor, devices=out)


def _symbol_table(args):
    from proteus844.route import plan as P
    from proteus844.build import writer  # noqa: F401  确保 vendor 已挂
    donor = args["donor"]
    from component_codec import Circuit
    c = Circuit(donor)
    rows = []
    for dev in sorted(c.templates):
        pins = P._symbol_pins(donor, dev)
        xs = [v[0] for v in pins.values()]
        ys = [v[1] for v in pins.values()]
        rows.append({"device": dev, "pins": len(pins),
                     "bbox": [min(xs), min(ys), max(xs), max(ys)],
                     "size": [max(xs) - min(xs), max(ys) - min(ys)]})
    return E.ok(rows=rows)


def _segments(args):
    import numpy as np
    from PIL import Image
    from proteus844.recognize import segments as S
    im = Image.open(args["image"]).convert("L")
    # 浅灰线会被固定阈值漏掉 —— 必须能调
    ink = np.array(im) < args.get("threshold", 140)
    raw = S.extract(ink, min_len=args.get("min_len", 12))
    return E.ok(horizontal=len(raw["horizontal"]), vertical=len(raw["vertical"]),
                segments=S.as_segments(raw))


def _junctions(args):
    import numpy as np
    from PIL import Image
    from proteus844.recognize import junctions as J
    im = Image.open(args["image"]).convert("L")
    ink = np.array(im) < 140
    dots = J.detect(ink, dot_peak=args.get("peak", 2.0))
    return E.ok(count=len(dots), junctions=dots)


def _validate(args):
    from proteus844 import validate as V
    return V.validate(args["netlist"], args["donor"])


def _plan(args):
    from proteus844.route import plan as P
    doc = P.plan(args["netlist"], args["donor"], args.get("min_spacing", 2))
    probs = P.check(doc)
    # 平行间距常常是器件引脚间距决定的（7410 三脚只隔 1 格），只当警告
    # 平行间距和共线重叠都只是观感问题（Proteus 按端点判连接，重叠不连通）
    warnings = [p for p in probs if "平行间距" in p or "共线重叠" in p]
    errors = [p for p in probs if "平行间距" not in p and "共线重叠" not in p]
    if errors:
        return E.fail(E.Code.ROUTE_OVERLAP, f"{len(errors)} 处问题",
                      problems=errors, plan=doc)
    return E.ok(plan=doc, warnings=warnings)


def _build(args):
    from proteus844.build import writer
    from proteus844.route import plan as RP
    plan_doc = args.get("plan")
    if plan_doc is None:
        # 不给 plan 就必须自己算：否则会走 vendor 自动布线，静默产出短接
        plan_doc = RP.plan(args["netlist"], args["donor"])
    res = writer.build(args["netlist"], plan_doc, args["donor"], args["out"])
    return E.ok(path=args["out"], size=os.path.getsize(args["out"]),
                planned=args.get("plan") is None,
                warnings=plan_doc.get("warnings", []) if isinstance(plan_doc, dict) else [],
                terminal_errors=res.get("terminal_errors", []))


def _trace(args):
    from proteus844.netlist import trace as T
    segs = [{"a": tuple(s["a"]), "b": tuple(s["b"])} for s in args["segments"]]
    juncs = args.get("junctions") or []
    pins = [{"ref": p["ref"], "pin": p["pin"], "tip": tuple(p["tip"])}
            for p in args["pins"]]
    boxes = [tuple(b) for b in (args.get("boxes") or [])]
    res = T.trace(segs, juncs, pins, tol=args.get("tol", 2.5), exclude_boxes=boxes)
    return E.ok(nets=res["nets"], unresolved=res["unresolved"],
                pieces=res["pieces"], nodes=res["nodes"])


def _probe_project(args):
    from proteus844 import version as V
    d = V.detect(args["project"])
    return E.ok(**d, text=V.format_probe(d))


def _review_layout(args):
    from proteus844 import beautify as B
    r = B.review_project(args["project"], args.get("donor"))
    return E.ok(**r, text=B.format_review(r))


def _check_overlap(args):
    from proteus844.verify import overlap as O
    segs, nwire = O.load(args["project"])
    findings = []
    import itertools
    for grp in ([x for x in segs if x["h"]], [x for x in segs if x["v"]]):
        for a, b in itertools.combinations(grp, 2):
            ov = O.overlap(a, b)
            if ov <= 0:
                continue
            findings.append({"overlap_units": ov, "same_net": a["net"] == b["net"],
                             "net_a": a["net"], "net_b": b["net"],
                             "verdict": "同网冗余（电气无关）" if a["net"] == b["net"]
                                        else "异网重叠（看原图判断）"})
    return E.ok(wires=nwire, findings=findings,
                note="重叠不等于短路：Proteus 按端点判连接，实测过")


def _verify_recognition(args):
    from proteus844.verify import pin_dirs as PD
    return PD.compare(args["image"], args["project"], args["netlist"],
                      args["components"], args["donor"], args["px_per_grid"])


def _pin_hints(args):
    from PIL import Image
    import numpy as np
    from proteus844.recognize import segments as S
    from proteus844.recognize import preprocess as PP
    from proteus844.recognize import hints as H
    gray = np.array(Image.open(args["image"]).convert("L"))
    ink, th, _ = PP.wire_mask(gray)
    segs = S.as_segments(S.extract(ink, min_len=args.get("min_len", 3)))
    res = H.annotate(args["image"], segs, args["bbox"], args["out_png"],
                     scale=args.get("scale", 8), max_points=args.get("max_points", 80))
    res["text"] = H.as_text(res)
    return res


def _check_against_image(args):
    from PIL import Image
    import numpy as np
    from proteus844.recognize import segments as S
    from proteus844.recognize import preprocess as PP
    from proteus844.verify import against_image as A
    gray = np.array(Image.open(args["image"]).convert("L"))
    if args.get("preprocess", True):
        ink, th, _ = PP.wire_mask(gray, base=args.get("threshold", 140))
    else:
        ink = gray < args.get("threshold", 140)
    segs = S.as_segments(S.extract(ink, min_len=args.get("min_len", 6)))
    return A.check_local(args["components"], args["netlist"], segs)


def _build_topology(args):
    from proteus844 import pipeline
    return pipeline.build_from_topology(args["netlist"], args["donor"], args["out"],
                                        verbose=False)


def _verify_file(args):
    from proteus844.verify import file_netlist as F
    return F.diff(args["netlist"], args["project"])


def _draw(args):
    from proteus844 import pipeline
    return pipeline.draw(args["image"], args["out"], args["donor"],
                         args["components"], args["px_per_grid"],
                         tol=args.get("tol", 2.5), verbose=False)


def _verify_structural(args):
    from proteus844.verify import structural
    return E.ok(text=structural.report(args["project"]))


def _verify_netdiff(args):
    """复用 verify/netdiff 的解析：返回逐网 OK/SHORT/BROKEN"""
    import subprocess
    import tempfile
    sdf = args["sdf"]
    if not os.path.exists(sdf):
        return E.fail(E.Code.BAD_ARGUMENT, f"SDF 不存在: {sdf}")
    if os.path.getsize(sdf) < 32:
        return E.fail(E.Code.BAD_ARGUMENT, f"SDF 太小，不像编出来的: {sdf}")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(args["netlist"], f, ensure_ascii=False)
        tmp = f.name
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "verify", "netdiff.py"),
                            tmp, args["sdf"]], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        ok = (r.returncode == 0) and ("电气一致" in r.stdout)
        if not ok:
            return E.fail(E.Code.NET_BROKEN,
                          f"netdiff 判定不一致（exit {r.returncode}）",
                          output=r.stdout.strip()[-800:])
        return E.ok(exit_code=0, output=r.stdout.strip())
    finally:
        os.unlink(tmp)


HANDLERS = {
    "donor_info": _donor_info, "symbol_table": _symbol_table,
    "recognize_segments": _segments, "recognize_junctions": _junctions,
    "validate_netlist": _validate, "plan_route": _plan, "build": _build,
    "trace": _trace, "probe_project": _probe_project, "review_layout": _review_layout, "check_overlap": _check_overlap,
    "build_topology": _build_topology,
    "pin_hints": _pin_hints,
    "check_against_image": _check_against_image,
    "verify_file": _verify_file, "verify_recognition": _verify_recognition,
    "draw": _draw,
    "verify_structural": _verify_structural, "verify_netdiff": _verify_netdiff,
}
for _n, _f in list(HANDLERS.items()):
    HANDLERS[_n] = E.guard(_f)


# ---------------- JSON-RPC ----------------

def handle(req):
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "proteus844", "version": VERSION}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        fn = HANDLERS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"未知工具 {name}"}}
        result = fn(params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(result, ensure_ascii=False)}],
                           "isError": not result.get("ok", False)}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"未知方法 {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700,
                                                   "message": "解析失败"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
