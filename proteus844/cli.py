"""proteus844 —— 原理图识别 / 建网 / 生成 / 验证工具链（M1 CLI）。

子命令：
    seg     图片 → 横竖线段
    junc    图片 → 实心结点
    pins    器件 + 已知引脚尖 → 全部引脚尖像素坐标
    trace   线段 + 结点 + 引脚尖 → 网络表
    build   网络表 → .pdsprj
    verify  生成的工程 → 结构 / 网表比对
    donors  列出内置供体工程
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor", "ref844"))

DEFAULT_DONOR = os.path.join(HERE, "donors", "base.pdsprj")


def _ink(path, scale=1, threshold=140):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("L")
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    a = np.array(im)
    return (a < 140), (a.shape[1] / scale, a.shape[0] / scale)


def cmd_probe(args):
    """这个工程是哪个 Proteus 版本？本工具支不支持？"""
    from proteus844 import version as V
    d = V.detect(args.project)
    print(V.format_probe(d))
    return 0 if d["supported"] else 1


def cmd_review(args):
    """体检一张画好的图：居不居中、装不装得下、绕不绕、有没有跨网共线。"""
    from proteus844 import beautify as B
    r = B.review_project(args.project, args.donor)
    print(B.format_review(r))
    return 0 if r.get("ok") else 1


def cmd_seg(args):
    from recognize import segments as S
    ink, _ = _ink(args.image, threshold=getattr(args, "threshold", 140))
    raw = S.extract(ink, min_len=args.min_len)
    segs = S.as_segments(raw)
    print(f"横线 {len(raw['horizontal'])} 条，竖线 {len(raw['vertical'])} 条")
    for s in segs:
        print(f"  ({s['a'][0]:6.1f},{s['a'][1]:6.1f}) -> ({s['b'][0]:6.1f},{s['b'][1]:6.1f})")
    if args.out:
        json.dump(segs, open(args.out, "w", encoding="utf-8"), indent=1)
        print("已写出", args.out)


def cmd_junc(args):
    from recognize import junctions as J
    ink, _ = _ink(args.image)
    dots = J.detect(ink, dot_peak=args.peak)
    print(f"实心结点 {len(dots)} 个")
    for d in dots:
        print(f"  ({d['x']:6.1f},{d['y']:6.1f})  peak={d['peak']:.2f}")
    if args.out:
        json.dump(dots, open(args.out, "w", encoding="utf-8"), indent=1)
        print("已写出", args.out)


def cmd_pins(args):
    from recognize import pins as P
    comps = json.load(open(args.components, encoding="utf-8-sig"))
    tips = P.predict(comps, args.donor, args.px_per_grid)
    flat = []
    for c in tips:
        print(f"  {c['ref']:8} anchor={tuple(round(v,1) for v in c['anchor_px'])}")
        for name, xy in c["pins"].items():
            print(f"      {name:6} {tuple(round(v,1) for v in xy)}")
            flat.append({"ref": c["ref"], "pin": name, "tip": list(xy)})
    if args.out:
        json.dump(flat, open(args.out, "w", encoding="utf-8"), indent=1)
        print("已写出", args.out)


def cmd_trace(args):
    from netlist import trace as T
    segs = json.load(open(args.segments, encoding="utf-8-sig"))
    juncs = json.load(open(args.junctions, encoding="utf-8-sig")) if args.junctions else []
    pins = json.load(open(args.pins, encoding="utf-8-sig"))
    if isinstance(pins, dict):                     # 兼容 {components:[{pins:{名字:坐标}}]}
        flat = []
        for c in pins.get("components", []):
            for name, xy in (c.get("pins") or {}).items():
                flat.append({"ref": c["ref"], "pin": name, "tip": xy})
        pins = flat
    segs = [{"a": tuple(s["a"]), "b": tuple(s["b"])} for s in segs]
    pins = [{"ref": p["ref"], "pin": p["pin"], "tip": tuple(p["tip"])} for p in pins]
    boxes = []
    if getattr(args, "boxes", None):
        boxes = [tuple(b) for b in json.load(open(args.boxes, encoding="utf-8-sig"))]
    res = T.trace(segs, juncs, pins, tol=args.tol, exclude_boxes=boxes)
    print(f"线段 {len(segs)} → 切成 {res['pieces']} 段，节点 {res['nodes']} 个")
    print(f"网络 {len(res['nets'])} 个：")
    for n in res["nets"]:
        print("   ", n["pins"])
    if res["unresolved"]:
        print(f"未决 {len(res['unresolved'])} 项：")
        for u in res["unresolved"]:
            print("   ", u)
    if args.out:
        json.dump(res, open(args.out, "w", encoding="utf-8"), indent=1)
        print("已写出", args.out)


def cmd_build(args):
    """默认先 plan_route 再按计划写盘 —— 和 MCP 的 build 走同一条路。"""
    from proteus844.route import plan as P
    from proteus844.build import writer
    spec = json.load(open(args.netlist, encoding="utf-8-sig"))
    donor = args.donor or DEFAULT_DONOR
    plan_doc = None
    if args.plan:
        plan_doc = json.load(open(args.plan, encoding="utf-8-sig"))
    elif not args.no_plan:
        plan_doc = P.plan(spec, donor)
        probs = P.check(plan_doc)
        hard = [p for p in probs if "平行间距" not in p]
        warn = [p for p in probs if "平行间距" in p]
        if hard:
            print(f"[FAIL] 布线问题 {len(hard)} 处:")
            for p in hard[:5]:
                print("   ", p)
        if warn:
            print(f"⚠ 可读性提示 {len(warn)} 处（多半是器件引脚间距决定，可忽略）：")
            for p in warn[:3]:
                print("   ", p)
    res = writer.build(spec, plan_doc, donor, args.out)
    print(f"已写出 {args.out}")
    if not args.no_plan:
        print(f"  布线：{'plan_route 自动规划' if not args.plan else '按给定方案'}")
    for e in res.get("terminal_errors", []):
        print(f"  ⚠ 终端没加上: {e['terminal']} — {e['error']}")


def cmd_verify(args):
    from verify import structural
    print(structural.report(args.project))


def cmd_init(args):
    from proteus844 import init_skill
    print(init_skill.report(args.skill_dir, force=args.force))


def cmd_verify_file(args):
    from proteus844.verify import file_netlist as F
    import json as _j
    nl = _j.load(open(args.netlist, encoding="utf-8-sig"))
    res = F.diff(nl, args.project)
    print(f"{args.project}: 器件 {res['components']} / 导线 {res['wires']} / "
          f"重建网 {res['rebuilt_nets']}")
    print(f"汇总 {res['summary']}")
    for n in res["nets"]:
        if n["status"] != "OK":
            print(f"  {n['status']:8} {n['net']}  "
                  f"{n.get('extra_pins') or n.get('found')}")
    print("判定:", "[OK] 电气一致" if res["ok"] else "[FAIL] 与意图不符")
    return 0 if res["ok"] else 1


def cmd_draw(args):
    from proteus844 import pipeline
    import json as _j
    comps = _j.load(open(args.components, encoding="utf-8-sig"))
    segs = None
    if args.segments:
        segs = _j.load(open(args.segments, encoding="utf-8-sig"))
    ppg = args.ppg or pipeline.estimate_ppg(comps, args.donor or DEFAULT_DONOR)
    if not ppg:
        print("❌ 推不出 px_per_grid，请用 --ppg 指定")
        return 1
    print(f"px_per_grid = {ppg}{'（自动推算）' if not args.ppg else ''}")
    res = pipeline.draw(args.image, args.out, args.donor or DEFAULT_DONOR,
                        comps, ppg, tol=args.tol, segments=segs,
                        threshold=args.threshold, min_len=args.min_len)
    if res.get("needs_user"):
        for k, v in res["needs_user"].items():
            print(f"  ⚠ {k}: {v}")
    return 0 if res.get("ok") else 1


def cmd_assemble(args):
    from proteus844 import pipeline
    comps = json.load(open(args.components, encoding="utf-8-sig"))
    nets = json.load(open(args.netlist, encoding="utf-8-sig"))
    if isinstance(nets, dict):
        nets = nets.get("nets", [])
    donor = args.donor or DEFAULT_DONOR
    # 没有坐标 = 只给了拓扑 → 自动布局路线
    if comps and all("x" not in c and "pins" not in c for c in comps):
        print("器件没有坐标，走自动布局（拓扑 → 工程）")
        res = pipeline.build_from_topology(
            {"components": comps, "nets": nets, "terminals": []}, donor, args.out)
        return 0 if res.get("ok") else 1
    ppg = args.ppg or pipeline.estimate_ppg(comps, donor)
    print(f"px_per_grid = {ppg}{'（自动推算）' if not args.ppg else ''}")
    res = pipeline.assemble(comps, nets, args.out, donor, ppg,
                            image=args.image, verbose=True)
    return 0 if res.get("ok") else 1


def cmd_donor_add(args):
    import shutil
    dst = os.path.join(HERE, "donors", args.name or os.path.basename(args.project))
    if not dst.endswith(".pdsprj"):
        dst += ".pdsprj"
    shutil.copy2(args.project, dst)
    from verify import structural
    print(f"已加入供体: {dst}")
    print(structural.report(dst).splitlines()[0])


def cmd_hints(args):
    from proteus844.recognize import hints as H
    from proteus844.recognize import preprocess as PP
    from proteus844.recognize import segments as S
    import numpy as np
    from PIL import Image
    bbox = [float(x) for x in args.bbox.split(",")]
    gray = np.array(Image.open(args.image).convert("L"))
    ink, th, dropped = PP.wire_mask(gray)
    segs = S.as_segments(S.extract(ink, min_len=args.min_len))
    r = H.annotate(args.image, segs, bbox, args.out, scale=args.scale)
    print(H.as_text(r))
    print(f"\\n阈值 {th} / 去文字 {dropped} 块 / 线段 {len(segs)}")
    return 0


def cmd_donors(args):
    d = os.path.join(HERE, "donors")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        print(" ", name)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proteus844", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="探测工程版本（FILEVER/RELEASE/CDB）")
    p.add_argument("project")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("review", help="体检：居中/装得下/绕线/共线")
    p.add_argument("project")
    p.add_argument("--donor", default=None, help="供体工程，用于精确估算符号占位")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("seg"); p.add_argument("image")
    p.add_argument("--min-len", type=int, default=12)
    p.add_argument("--threshold", type=int, default=140,
                   help="二值化阈值；140 抓深色线，浅灰线用 200")
    p.add_argument("--out")
    p.set_defaults(func=cmd_seg)

    p = sub.add_parser("junc"); p.add_argument("image")
    p.add_argument("--peak", type=float, default=2.0); p.add_argument("--out")
    p.set_defaults(func=cmd_junc)

    p = sub.add_parser("pins"); p.add_argument("--components", required=True)
    p.add_argument("--donor", default=DEFAULT_DONOR)
    p.add_argument("--px-per-grid", type=float, required=True)
    p.add_argument("--out"); p.set_defaults(func=cmd_pins)

    p = sub.add_parser("trace"); p.add_argument("--segments", required=True)
    p.add_argument("--junctions"); p.add_argument("--pins", required=True)
    p.add_argument("--tol", type=float, default=2.5)
    p.add_argument("--boxes", help="器件本体包围盒 JSON: [[x0,y0,x1,y1], ...]")
    p.add_argument("--out"); p.set_defaults(func=cmd_trace)

    p = sub.add_parser("build"); p.add_argument("netlist"); p.add_argument("out")
    p.add_argument("--donor")
    p.add_argument("--plan", help="用给定的布线方案 JSON")
    p.add_argument("--no-plan", action="store_true", help="不规划，交给自动布线（不推荐）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify"); p.add_argument("project"); p.set_defaults(func=cmd_verify)

    p = sub.add_parser("init")
    p.add_argument("--skill-dir", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("assemble")
    p.add_argument("components"); p.add_argument("netlist"); p.add_argument("out")
    p.add_argument("--donor"); p.add_argument("--ppg", type=float)
    p.add_argument("--image", help="给了就顺带做识别校验（需要引脚像素坐标）")
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("draw")
    p.add_argument("image"); p.add_argument("out")
    p.add_argument("--donor"); p.add_argument("--components", required=True)
    p.add_argument("--ppg", type=float, help="每格多少像素（不给就按 donor 符号推算）")
    p.add_argument("--segments", help="用给定的线段 JSON，不重新抽")
    p.add_argument("--threshold", type=int, default=140, help="二值化阈值（默认 140）")
    p.add_argument("--min-len", type=int, default=12, help="最短线段长度（默认 12）")
    p.add_argument("--tol", type=float, default=2.5)
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("verify-file")
    p.add_argument("project"); p.add_argument("--netlist", required=True)
    p.set_defaults(func=cmd_verify_file)

    p = sub.add_parser("donor-add")
    p.add_argument("project")
    p.add_argument("--name")
    p.set_defaults(func=cmd_donor_add)

    p = sub.add_parser("hints", help="放大标注一个器件，列出候选端点编号+坐标")
    p.add_argument("image")
    p.add_argument("--bbox", required=True, help="x0,y0,x1,y1")
    p.add_argument("--out", default="hint.png")
    p.add_argument("--scale", type=int, default=8)
    p.add_argument("--min-len", dest="min_len", type=int, default=3)
    p.set_defaults(func=cmd_hints)

    p = sub.add_parser("donors"); p.set_defaults(func=cmd_donors)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
