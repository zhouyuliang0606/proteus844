"""结构自检：读回生成的 .pdsprj，列出器件与坐标（不依赖 Proteus）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def report(path):
    import verify.reader as R
    recs, buf = R.parse(path)
    lines = [f"{path}: {len(recs)} 个器件, DSN {len(buf)} B"]
    for r in recs:
        lines.append(f"  {r['ref'] or '(空)':10} {r['device']:16} "
                     f"{str(r['value']):10} ({r['x']/254000:6.1f},{r['y']/254000:6.1f}) "
                     f"rot={r['rotation']}")
    return "\n".join(lines)
