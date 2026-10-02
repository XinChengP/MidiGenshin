"""导出 txt 时序脚本（规范见需求文档 §6）。"""

from __future__ import annotations

import os

from .keys import KEY_NAMES
from .mapper import MapParams, MapResult

FORMAT_VERSION = "genshin-lyre-script v1"


def _fmt_sec(t: float) -> str:
    return f"{t:.3f}"


def _fmt_clock(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


def export_script(
    result: MapResult,
    params: MapParams,
    path: str,
    *,
    source_name: str = "",
    include_header: bool = True,
    clock_format: bool = False,   # False: 秒；True: 分:秒.毫秒
    speed: float = 1.0,           # >1 表示更快，时间等比缩短
) -> int:
    """写出到 path，返回事件行数。"""
    if speed <= 0:
        raise ValueError("演奏速度必须大于 0")
    fmt = _fmt_clock if clock_format else _fmt_sec
    lines: list[str] = []
    if include_header:
        s = result.stats
        snap = {"down": "snap-down", "up": "snap-up", "drop": "drop"}[params.snap]
        lines += [
            f"# {FORMAT_VERSION}",
            f"# source={source_name}" if source_name else "# source=",
            f"# instrument={params.instrument.name}",
            f"# duration={_fmt_sec(max((e.time for e in result.events), default=0.0))}s",
            f"# transpose={params.transpose}  blackkey={snap}  "
            f"chord-tolerance={int(round(params.chord_tol * 1000))}ms  speed={int(round(speed * 100))}%",
            f"# events={len(result.events)}  notes={s.kept}  dropped={s.dropped}",
        ]
    for e in result.events:
        t = e.time / speed
        lines.append(f"{fmt(t)}\t{e.combo}")
    data = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return len(result.events)


def validate_script_keys(text: str) -> list[str]:
    """校验外部脚本键名是否合法，返回非法键名列表（供回读功能使用）。"""
    bad = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        for key in line.split("\t")[-1].split("+"):
            if key and key not in KEY_NAMES and key not in bad:
                bad.append(key)
    return bad
