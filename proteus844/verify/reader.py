import os
"""rev844 正式解析器：从 .pdsprj 直接产出器件表。

    {ref, device, value, x, y, rotation, index, pin_count, symbol, dsn_offset, instance_offset}

已确认布局（见 FIELD_MAP.md，left4 已与官方 SDF 的 *PARTLIST 逐条对上 9/9）：

  DSN 记录：
    [tag:1B] ff<ref> <32B 文本尾> ff<字体> "COMPONENT ID\\0"   u32 ff<value>  <32B 尾> ff<字体>
             "COMPONENT VALUE\\0" u32 ff<device> <32B 尾> ff<字体>
             "SUBCKT NAME\\0"     u32 ff<subckt> <32B 尾> ff<字体>
             "PROPERTIES\\0"      u32 ff<props>  <32B 尾> ff<字体>
             <u32 props_len> <u16 pin_count> <u8 sym_len> <symbol>
             <i32 x><i32 y><u32 rot><u32 index><9 个 0><pin nets 4B/脚>

  坐标：254000 = 100mil = 1 格；100000 = 1mm；DSN 小端，CDB 大端。
  注意：844 的 "COMPONENT ID" 装的是 value、"COMPONENT VALUE" 装的是 device（与 847 参考实现相反）。
        LOGICSTATE 这类对象的 ref 为空，Proteus 用 "<device>#<index:04d>" 合成。
"""
import sys
import zipfile

GRID = 254000


def load(path):
    with zipfile.ZipFile(path) as z:
        return z.read("ROOT.DSN")


def find_all(buf, needle):
    out, i = [], 0
    while True:
        k = buf.find(needle, i)
        if k < 0:
            return out
        out.append(k)
        i = k + 1


def ff_at(buf, p):
    """若 p 处是 ff <len> <printable>，返回 (text, end)；否则 None。"""
    if p >= len(buf) or buf[p] != 0xFF:
        return None
    n = buf[p + 1]
    if n > 0x40:
        return None
    body = buf[p + 2:p + 2 + n]
    if len(body) != n or (n and not all(32 <= b < 127 for b in body)):
        return None
    return body.decode("ascii"), p + 2 + n


def ff_after(buf, start, window=64):
    for p in range(start, min(len(buf), start + window)):
        r = ff_at(buf, p)
        if r:
            return r[0], p
    return None, start


def find_ref(buf, id_off, back=260):
    """COMPONENT ID 之前最后一个『ff 值 + 32B 文本尾 + 紧接另一个 ff（字体值）』。"""
    best = ("", -1)
    for p in range(max(0, id_off - back), id_off):
        r = ff_at(buf, p)
        if not r or r[0].__len__() > 12:
            continue
        q = r[1] + 32
        if q < len(buf) and buf[q] == 0xFF:
            best = (r[0], p)
    return best


def instances(buf):
    """结构签名：<u16 pin_count><u8 sym_len><symbol><i32 x><i32 y><u32 rot><u32 idx><全 0 区>

    rot 单位是**十分之一度**：0 / 900 / 1800 / 2700 = 0° / 90° / 180° / 270°。
    """
    out = []
    for p in range(24, len(buf) - 20):
        rot = int.from_bytes(buf[p + 8:p + 12], "little")
        idx = int.from_bytes(buf[p + 12:p + 16], "little")
        if rot % 900 or rot >= 3600 or not (1 <= idx <= 32):
            continue
        found = None
        for L in range(1, 41):
            if p - 1 - L < 3:
                break
            if buf[p - 1 - L] != L:
                continue
            sym = buf[p - L:p]
            if all(32 <= b < 127 for b in sym):
                found = (L, sym.decode())
                break
        if not found:
            continue
        L, sym = found
        pins = int.from_bytes(buf[p - L - 3:p - L - 1], "little")
        if not (1 <= pins <= 64):
            continue
        if buf[p + 16:p + 20] != b"\x00" * 4:
            continue
        x = int.from_bytes(buf[p:p + 4], "little", signed=True)
        y = int.from_bytes(buf[p + 4:p + 8], "little", signed=True)
        out.append({"x": x, "y": y, "rot": rot, "idx": idx, "at": p,
                    "symbol": sym, "pins": pins})
    return out


def parse(path):
    buf = load(path)
    ids = find_all(buf, b"COMPONENT ID\x00")
    vals = find_all(buf, b"COMPONENT VALUE\x00")
    inst = instances(buf)
    recs = []
    for k, id_off in enumerate(ids):
        if k >= len(inst):
            break
        it = inst[k]
        ref, ref_off = find_ref(buf, id_off)
        value, _ = ff_after(buf, id_off + 12, 48)
        dev, _ = ff_after(buf, vals[k] + 15, 48) if k < len(vals) else (None, 0)
        recs.append({"ref": ref, "device": dev, "value": value,
                     "x": it["x"], "y": it["y"], "rotation": it["rot"],
                     "index": it["idx"], "pin_count": it["pins"],
                     "symbol": it["symbol"],
                     "dsn_offset": id_off, "instance_offset": it["at"],
                     "ref_offset": ref_off})
    return recs, buf


def display_ref(r):
    return r["ref"] or f"{r['device']}#{r['index']:04d}"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        raise SystemExit("用法: python -m proteus844.verify.reader <工程.pdsprj>")
    recs, buf = parse(path)
    print(f"{path}  DSN={len(buf)}  器件 {len(recs)}\n")
    hdr = (f"{'idx':>3} {'ref':18} {'device':10} {'value':8} {'symbol':10} {'pin':>3} "
           f"{'x':>10} {'y':>10} {'gx':>4} {'gy':>4} rot {'id_off':>7} {'inst_off':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(recs, key=lambda r: r["index"]):
        print(f"{r['index']:3} {display_ref(r):18} {str(r['device']):10} "
              f"{str(r['value']):8} {r['symbol']:10} {r['pin_count']:3} "
              f"{r['x']:10} {r['y']:10} {r['x']//GRID:4} {r['y']//GRID:4} "
              f"{r['rotation']:3} {r['dsn_offset']:7} {r['instance_offset']:8}")


if __name__ == "__main__":
    main()
