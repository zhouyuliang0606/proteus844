"""按内容尺寸调整图纸大小。

Proteus 的图纸尺寸存在 ROOT.DSN 的 sheet header 里：
    "ISIS CIRCUIT FILE\\x1a\\x00" + 6 字节标志 + u32 宽 + u32 高（native 单位）
1 格 = 254000。

实测：A4 是 100×70 格（25400000 × 17812768）。
器件多到装不下时，把图纸改大即可 —— 比强行压缩布局靠谱。
"""
import io
import re
import shutil
import zipfile

G = 254000
MARK = b"ISIS CIRCUIT FILE\x1a\x00"


def read_sheet(path):
    from . import file_netlist as F
    buf = F.reader.load(path)
    i = buf.find(MARK)
    if i < 0:
        return None
    w = int.from_bytes(buf[i + 25:i + 29], "little")
    h = int.from_bytes(buf[i + 29:i + 33], "little")
    return {"width_grids": round(w / G, 1), "height_grids": round(h / G, 1),
            "offset": i + 25}


def resize_sheet(path, width_grids=None, height_grids=None):
    """就地改图纸尺寸。返回改前/改后。"""
    src = zipfile.ZipFile(path)
    members = {n: src.read(n) for n in src.namelist()}
    src.close()
    dsn = bytearray(members["ROOT.DSN"])
    i = dsn.find(MARK)
    if i < 0:
        raise ValueError("找不到 sheet header")
    old_w = int.from_bytes(dsn[i + 25:i + 29], "little")
    old_h = int.from_bytes(dsn[i + 29:i + 33], "little")
    if width_grids:
        dsn[i + 25:i + 29] = int(round(width_grids * G)).to_bytes(4, "little")
    if height_grids:
        dsn[i + 29:i + 33] = int(round(height_grids * G)).to_bytes(4, "little")
    members["ROOT.DSN"] = bytes(dsn)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    shutil.move(tmp, path)
    return {"from": [round(old_w / G, 1), round(old_h / G, 1)],
            "to": [round(int.from_bytes(dsn[i + 25:i + 29], "little") / G, 1),
                   round(int.from_bytes(dsn[i + 29:i + 33], "little") / G, 1)]}


def fit_to_content(path, margin=8, min_w=None, min_h=None):
    """按器件坐标范围把图纸调到刚好装得下。

    最小尺寸默认取**当前图纸尺寸**（不要把 A4 当成硬下限 ——
    内容本来就装得下时不该把图纸撑大）。
    """
    from . import structural
    cur = read_sheet(path) or {"width_grids": 100.0, "height_grids": 70.0}
    lines = structural.report(path).splitlines()
    xs = [float(l.split("(")[1].split(",")[0]) for l in lines[1:] if "(" in l]
    ys = [float(l.split(",")[1].split(")")[0]) for l in lines[1:] if "(" in l]
    if not xs:
        return None
    # 页框以中心为原点，所以要按「绝对值的两倍」算需要的尺寸，
    # 而不是 max(x) —— 否则负方向的内容会溢出。
    need_w = max(min_w or cur["width_grids"], int(2 * (max(abs(v) for v in xs) + margin)))
    need_h = max(min_h or cur["height_grids"], int(2 * (max(abs(v) for v in ys) + margin)))
    return resize_sheet(path, need_w, need_h)


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    print("改前:", read_sheet(p))
    print("调整:", fit_to_content(p))
    print("改后:", read_sheet(p))
