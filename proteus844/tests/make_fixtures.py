"""生成 CLI 回归用的夹具（结点 / 引脚尖 / 包围盒），并跑一遍 CLI。"""
import json
import os
import subprocess
import sys

J = D = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

juncs = [{"x": 97.0, "y": 53.0}, {"x": 113.5, "y": 125.0},
         {"x": 115.5, "y": 205.0}, {"x": 363.5, "y": 135.0}]

PINS = [
    ("LS1", "Q0", [56, 52.5]), ("LS2", "Q0", [54, 125]), ("LS3", "Q0", [56, 205]),
    ("U1:D", "A", [149, 52.5]), ("U1:D", "B", [149, 69.5]), ("U1:D", "Y", [204, 60.5]),
    ("U3:A", "A", [154, 125]), ("U3:A", "B", [154, 141.5]), ("U3:A", "Y", [210, 134]),
    ("U3:B", "A", [159, 205]), ("U3:B", "B", [159, 222]), ("U3:B", "Y", [215, 213.5]),
    ("U4:A", "A", [274, 126]), ("U4:A", "B", [274, 134]), ("U4:A", "C", [274, 142.5]),
    ("U4:A", "Y", [330, 134.5]),
    ("R14", "1", [363.5, 151]), ("R14", "2", [363.5, 175]),
    ("D2", "A", [363.5, 195]), ("D2", "K", [363.5, 238]),
]
pins = [{"ref": r, "pin": p, "tip": t} for r, p, t in PINS]

BOXES = [[149, 44, 187, 78], [154, 116, 194, 150], [159, 197, 199, 231],
         [274, 117, 314, 151], [356, 149, 371, 177], [350, 188, 378, 226],
         [34, 44, 50, 61], [34, 116, 48, 134], [36, 197, 50, 214]]

for name, data in (("_juncs_test.json", juncs), ("_pins_test.json", pins),
                   ("_boxes_test.json", BOXES)):
    json.dump(data, open(rf"{D}\{name}", "w", encoding="utf-8"), indent=1)
print("夹具已生成")

r = subprocess.run([sys.executable, "-m", "proteus844.cli", "trace",
                    "--segments", rf"{D}\_segs.json",
                    "--junctions", rf"{D}\_juncs_test.json",
                    "--pins", rf"{D}\_pins_test.json",
                    "--boxes", rf"{D}\_boxes_test.json",
                    "--out", rf"{D}\_trace_out.json"],
                   cwd=D, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip())
if r.returncode:
    print("STDERR:", r.stderr[-800:])
else:
    res = json.load(open(rf"{D}\_trace_out.json", encoding="utf-8"))
    print(f"\nCLI 输出：{len(res['nets'])} 网 / 未决 {len(res['unresolved'])} 项")
