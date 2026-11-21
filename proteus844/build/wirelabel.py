"""连线标号（WIRE LABEL）：按 Proteus 真实记录格式自己拼。

为什么不用 vendor 的 `label_record`：
它的属性块偏移与本机 Proteus 8.15 写出来的不一样，
拿真实尾部喂进去会被 `_text` 校验拒掉（Unexpected stored label suffix）。
所以这里直接按实测字节布局拼，并在运行时挂到 vendor 的 `wire_record` 上 ——
不改 vendor 源文件，只在我们的进程里替换该函数。

真实记录（从 Proteus 亲手保存的工程里挖出来的）：

    [wire 前缀 24B] 57 49 52 45 00      "WIRE\\0"
    [标号数量 u16]
    ff <len> <文字> <x:i32> <y:i32>     ← 文字与坐标
    <72 字节固定尾部>                    ← 字体 "Default Font" + "WIRE LABEL" + 样式
    ...
"""
import struct

# 从真实工程里挖出的、位于「坐标之后」的固定 72 字节
TAIL_AFTER_POSITION = bytes.fromhex(
    "0000000000003000000030e00300c0190300000000000120ff01"
    "44656661756c7420466f6e7400"
    "57495245204c4142454c0000"
    "000000000200501861ff20445500"
    "407974ff20445500"
)

WIRE_PREFIX = bytes.fromhex(
    "00 1d 00 00 00 00 c0 9e 00 00 00 40 00 00 01 ff ff ff 00 ff ff ff 00 02 7f"
) + b"WIRE\0\0\0"


def label_bytes(text, x, y):
    raw = text.encode("ascii")
    if not (0 < len(raw) < 255):
        raise ValueError("标号文字必须是 1~254 个 ASCII 字符")
    return b"\xff" + bytes([len(raw)]) + raw + struct.pack("<ii", int(x), int(y)) + TAIL_AFTER_POSITION


def wire_record(points, labels=()):
    """与 vendor 同签名；有 labels 时用真实格式编码。"""
    points = [tuple(p) for p in points]
    if not labels:
        # 没标号就交给原函数（保持行为完全一致）
        from wire_codec import _vendor_wire_record
        return _vendor_wire_record(points)

    from wire_codec import _vendor_wire_record
    base = _vendor_wire_record(points)          # 先拿一条合法的无标号记录
    encoded = b"".join(
        label_bytes(lab["text"], *(lab.get("position") or _midpoint(points)))
        for lab in labels)
    # 前缀最后 2 字节是「标号数」占位，换成真实数量再拼标号
    head = base[:len(WIRE_PREFIX) - 2] + struct.pack("<H", len(labels))
    rest = base[len(WIRE_PREFIX):]
    return head + encoded + rest


def _midpoint(points):
    """放在最长那条线段的中点（Proteus 自己也这么摆）。"""
    a, b = max(zip(points, points[1:]),
               key=lambda pq: abs(pq[0][0] - pq[1][0]) + abs(pq[0][1] - pq[1][1]))
    return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)


def install():
    """把我们的实现挂到 vendor 的 wire_codec 上（进程内生效，不改源文件）。"""
    import wire_codec
    if getattr(wire_codec, "_label_patched", False):
        return
    wire_codec._vendor_wire_record = wire_codec.wire_record
    wire_codec.wire_record = wire_record
    wire_codec._label_patched = True
