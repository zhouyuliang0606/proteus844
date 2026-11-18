"""donor 体检：它里面还剩多少器件和导线。

donor 的用途只是提供**器件模板**，它本身必须是一张空图；
否则生成出来的工程会叠加 donor 原有的电路（这是最难发现的坑）。
"""
import re


def check(donor):
    from . import file_netlist as F
    buf = F.reader.load(donor)
    recs, _ = F.reader.parse(donor)
    wires = len(re.findall(b"WIRE", buf))
    return {
        "donor": donor,
        "components": len(recs),
        "wires": wires,
        "empty": len(recs) == 0 and wires <= 4,
        # 实测：donor 的内容**不会**进输出（_enc6 正好 22 个器件、_reg3 正好 9 个）。
        # 但 donor 太杂会让排查变困难，所以只提示不建议强改。
        "advice": ("donor 干净。" if len(recs) == 0 and wires <= 4 else
                   f"donor 里还有 {len(recs)} 个器件 / {wires} 条导线；"
                   "实测它们不会进输出，只是排查时容易混淆。"),
    }
