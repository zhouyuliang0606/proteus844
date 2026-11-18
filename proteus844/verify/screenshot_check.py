"""验收器 v3：结构张量求局部线方向，区分 轴向(0°/90°) 和 斜向(≈45°)。

为什么前两版不行：
  v1 "对角连通" → 3px 粗线的边缘天然有对角邻居，误判
  v2 "长对角游程" → 粗线边缘同样产生长游程，全被误判

结构张量是对的做法：窗口内梯度方向的分布决定线的朝向，
粗线、细线、拐角都不影响判断。
"""
import sys

import numpy as np
from PIL import Image


def green_mask(path):
    im = np.array(Image.open(path).convert("RGB")).astype(float)
    r, g, b = im[:, :, 0], im[:, :, 1], im[:, :, 2]
    return ((g > 60) & (g < 190) & (r < 110) & (b < 110)
            & (g - r > 25) & (g - b > 25)).astype(float)


def blur(a, k=2):
    """简单盒式模糊（够用，不引 scipy 依赖）"""
    out = a.copy()
    for _ in range(k):
        out = (out
               + np.roll(out, 1, 0) + np.roll(out, -1, 0)
               + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def analyse(path, verbose=False):
    m = green_mask(path)
    if m.sum() < 50:
        # 空图/几乎没导线 → 不能判通过，只能判"无法判定"
        return {"file": path.split("\\")[-1], "green_pixels": int(m.sum()),
                "diag_energy_ratio": None,
                "verdict": "⚠ 画面里几乎没有导线，无法判定（不要当通过）"}
    gy, gx = np.gradient(blur(m, 1))
    jxx = blur(gx * gx, 2)
    jyy = blur(gy * gy, 2)
    jxy = blur(gx * gy, 2)
    tr = jxx + jyy
    tmp = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
    coh = np.where(tr > 1e-6, tmp / np.maximum(tr, 1e-9), 0)     # 方向一致性
    theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy)                  # 梯度主方向
    theta_deg = np.degrees(theta) % 180

    strong = (m > 0) & (coh > 0.4) & (tr > 1e-8)
    if not strong.any():
        return {"file": path.split("\\")[-1], "green_pixels": int(m.sum()),
                "diag_energy_ratio": 0.0, "verdict": "✅ 正常"}

    # 线上像素的梯度方向垂直于线本身：线水平→梯度竖直(90)，线竖直→梯度水平(0)
    line_deg = (theta_deg + 90) % 180
    axis = ((line_deg < 12) | (line_deg > 168)
            | ((line_deg > 78) & (line_deg < 102)))
    diag = (line_deg > 25) & (line_deg < 65) | (line_deg > 115) & (line_deg < 155)

    w = tr * coh
    total = float(w[strong].sum())
    ratio = float(w[strong & diag].sum()) / max(total, 1e-9)
    return {
        "file": path.split("\\")[-1],
        "green_pixels": int(m.sum()),
        "axis_energy": round(float(w[strong & axis].sum()) / max(total, 1e-9), 4),
        "diag_energy_ratio": round(ratio, 4),
        "verdict": ("❌ 有斜线" if ratio > 0.15 else
                    "✅ 本视口内正交" if int(m.sum()) > 400 else
                    "⚠ 导线像素太少，结果不可靠"),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m proteus844.verify.screenshot_check <截图.png>")
    for p in sys.argv[1:]:
        print(analyse(p))
