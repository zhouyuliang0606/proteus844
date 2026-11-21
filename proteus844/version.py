"""版本探针：读一个 .pdsprj，说清它是哪个版本、本工具支不支持。

写入布局是按 FILEVER 分支的，不同版本的结构不完全一样：

    RELEASE / FILEVER        结构模板
    814     / 840            已验证（上游 proteus-automatic-api）
    815     / 844            已验证（本项目逆向补上）
    816     / 847            已验证（上游）
    其它                      未验证 —— 用 probe 看差在哪

加了新版本之后，跑 `python -m proteus844.tests.regression` 确认没把旧版本改坏。
"""
import struct
import zipfile

SUPPORTED = {
    "840": "Proteus 8.14（上游已验证）",
    "844": "Proteus 8.15（本项目逆向补上）",
    "847": "Proteus 8.16（上游已验证）",
}

# 各版本对应的 RELEASE 号（PROJECT.XML 里同时有 RELEASE 和 FILEVER）
RELEASE_OF = {"840": "814", "844": "815", "847": "816"}


def read_xml(project):
    with zipfile.ZipFile(project) as z:
        return z.read("PROJECT.XML").decode("utf-8", "replace")


def detect(project):
    """返回版本事实。不做校验，读不出来就填 None。"""
    out = {"path": project, "filever": None, "release": None, "cdb_version": None,
           "dsn_bytes": None, "members": [], "supported": False, "hint": None}
    try:
        with zipfile.ZipFile(project) as z:
            out["members"] = z.namelist()
            xml = z.read("PROJECT.XML").decode("utf-8", "replace")
            cdb = z.read("ROOT.CDB")
            dsn = z.read("ROOT.DSN")
    except Exception as exc:                                  # noqa: BLE001
        out["hint"] = f"不是可读的 .pdsprj：{exc}"
        return out

    import re
    m = re.search(r'RELEASE="(\d+)"\s+FILEVER="(\d+)"', xml)
    if m:
        out["release"], out["filever"] = m.group(1), m.group(2)
    else:
        v = re.search(r'FILEVER="(\d+)"', xml)
        r = re.search(r'RELEASE="(\d+)"', xml)
        out["filever"] = v.group(1) if v else None
        out["release"] = r.group(1) if r else None

    if len(cdb) >= 8:
        out["cdb_version"] = struct.unpack("<I", cdb[:4])[0]
    out["dsn_bytes"] = len(dsn)
    out["dsn_header"] = dsn[:16].decode("latin-1", "replace").strip("\x00")

    fv = out["filever"]
    out["supported"] = fv in SUPPORTED
    if out["supported"]:
        out["hint"] = f"✅ {SUPPORTED[fv]}"
    elif fv:
        out["hint"] = (
            f"❌ FILEVER {fv}（RELEASE {out['release']}）没有验证过。"
            f"本工具支持 {sorted(SUPPORTED)}。\n"
            f"   两条路：\n"
            f"   1) 用你自己的 Proteus 存一个工程当 donor —— 但写入布局仍按版本分支，"
            f"多数情况下需要适配新模板；\n"
            f"   2) 按下面的结构差异补一个分支（见 skill §8）。"
        )
    else:
        out["hint"] = "❌ 读不到 FILEVER，可能不是 Proteus 工程"
    return out


def format_probe(d):
    lines = [f"{d['path']}"]
    lines.append(f"  RELEASE {d['release']}   FILEVER {d['filever']}   "
                 f"CDB v{d['cdb_version']}   DSN {d['dsn_bytes']} 字节")
    lines.append(f"  成员 {', '.join(d['members'])}")
    if d.get("dsn_header"):
        lines.append(f"  DSN 头 {d['dsn_header']!r}")
    for line in (d["hint"] or "").splitlines():
        lines.append("  " + line)
    return "\n".join(lines)


def guard(project):
    """不支持就直接给出人话，别再抛原始 traceback。"""
    d = detect(project)
    if not d["supported"]:
        raise SystemExit(format_probe(d))
    return d
