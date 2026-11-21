import os
"""从 donor 导出「符号尺寸表」：每个器件的引脚尖端坐标、包围盒、推荐标尺对。

用途：识别时用它把像素换算成格，不用现场量、不靠估。
    px_per_grid = 图上该器件包围盒像素宽 / 表里的包围盒宽(格)

用法:
    python symbol_table.py                 # 用默认 donor
    python symbol_table.py donor.pdsprj
    python symbol_table.py donor.pdsprj --md   # 输出 markdown 表
"""
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "ref844"))
from component_codec import Circuit

G = 254000
DEFAULT_DONORS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "donors", "kit.pdsprj"),
]


def table(donor):
    c = Circuit(donor)
    out = {}
    for i, device in enumerate(sorted(c.templates), 1):
        ref = f"Z{i}:A"
        try:
            c.add(device=device, ref=ref, value=device, x=0, y=0)
        except Exception as exc:                      # 该型号不能这样放，跳过
            out[device] = {"error": str(exc)}
            continue
        pins = {p["name"]: (p["position"][0] // G, p["position"][1] // G)
                for p in c.pins(ref)}
        xs = [v[0] for v in pins.values()]
        ys = [v[1] for v in pins.values()]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        # 推荐标尺对：纵向间距最大的两个引脚（间距越大，量出来误差越小）
        best, pair = 0, None
        names = list(pins)
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                dx = abs(pins[names[a]][0] - pins[names[b]][0])
                dy = abs(pins[names[a]][1] - pins[names[b]][1])
                d = max(dx, dy)
                if d > best:
                    best, pair = d, (names[a], names[b], d)
        out[device] = {"pins": pins, "bbox": bbox,
                       "size": (bbox[2] - bbox[0], bbox[3] - bbox[1]),
                       "ruler": pair}
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    md = "--md" in sys.argv
    donors = args or DEFAULT_DONORS
    for donor in donors:
        from . import version as V
        V.guard(donor)
        t = table(donor)
        print(f"\n### {donor}\n")
        if md:
            print("| 器件 | 引脚数 | 引脚尖(格) | 尺寸(格) | 推荐标尺 |")
            print("|---|---|---|---|---|")
            for dev, info in t.items():
                if "error" in info:
                    print(f"| `{dev}` | — | 放不进去: {info['error'][:40]} | — | — |")
                    continue
                pins = " ".join(f"{k}({v[0]},{v[1]})" for k, v in info["pins"].items())
                r = info["ruler"]
                size = f"{info['size'][0]}×{info['size'][1]}"
                print(f"| `{dev}` | {len(info['pins'])} | {pins} | {size} | "
                      f"{r[0]}↔{r[1]} = {r[2]} 格 |" if r else
                      f"| `{dev}` | {len(info['pins'])} | {pins} | {size} | — |")
        else:
            for dev, info in t.items():
                if "error" in info:
                    print(f"  {dev:22} 放不进去: {info['error'][:60]}")
                    continue
                r = info["ruler"]
                print(f"  {dev:22} 引脚 {len(info['pins']):2}  尺寸 {info['size']}  "
                      f"标尺 {r[0]}↔{r[1]}={r[2]}格" if r else
                      f"  {dev:22} 引脚 {len(info['pins']):2}  尺寸 {info['size']}")


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    donors = args or DEFAULT_DONORS
    want_md = "--md" in sys.argv
    for d in donors:
        from . import version as V
        V.guard(d)                      # 版本不支持就给人话，别抛 traceback
        print(table(d) if not want_md else table(d))
