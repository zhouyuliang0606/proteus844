

# 控制台是 GBK（中文 Windows 默认）时，打印 ✅/❌ 会抛 UnicodeEncodeError。
# 统一把标准输出改成 UTF-8，失败就退化成替换字符，不让程序崩。
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
