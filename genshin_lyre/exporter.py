"""导出 txt 时序脚本（规范见需求文档 §6）。"""

from __future__ import annotations

import math
import os

from .keys import KEY_NAMES
from .mapper import TAP_HOLD, MapParams, MapResult

FORMAT_VERSION = "genshin-lyre-script v1"


def _fmt_sec(t: float) -> str:
    return f"{t:.3f}"


def _fmt_clock(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


def parse_time(text: str) -> float:
    """解析时间文本为秒：'83'、'1:23'、'1:23.5' 均可；拒绝负数与非有限值。

    供脚本回读与界面时间跳转共用；非法输入抛 ValueError。
    """
    text = text.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"时间格式无效：{text!r}")
        t = int(parts[0]) * 60 + float(parts[1])
    else:
        t = float(text)
    if not math.isfinite(t) or t < 0:
        raise ValueError(f"时间必须是非负有限数：{text!r}")
    return t


def export_script(
    result: MapResult,
    params: MapParams,
    path: str,
    *,
    source_name: str = "",
    include_header: bool = True,
    clock_format: bool = False,   # False: 秒；True: 分:秒.毫秒
    speed: float = 1.0,           # >1 表示更快，时间等比缩短
    include_durations: bool = False,  # v2：附加保持时长列，回读可“跟随音符”
) -> int:
    """写出到 path，返回事件行数。"""
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("演奏速度必须是有限正数")
    fmt = _fmt_clock if clock_format else _fmt_sec
    lines: list[str] = []
    if include_header:
        s = result.stats
        snap = {"down": "snap-down", "up": "snap-up", "drop": "drop"}[params.snap]
        version = "genshin-lyre-script v2" if include_durations else FORMAT_VERSION
        lines += [
            f"# {version}",
            f"# source={source_name}" if source_name else "# source=",
            f"# instrument={params.instrument.name}",
            f"# duration={_fmt_sec(max((e.time for e in result.events), default=0.0))}s",
            f"# transpose={params.transpose}  blackkey={snap}  "
            f"chord-tolerance={int(round(params.chord_tol * 1000))}ms  speed={int(round(speed * 100))}%",
            f"# events={len(result.events)}  notes={s.kept}  dropped={s.dropped}",
        ]
    for e in result.events:
        t = e.time / speed
        row = f"{fmt(t)}\t{e.combo}"
        if include_durations:
            hold = TAP_HOLD if params.hold_mode == "tap" else e.hold / speed
            row += f"\t{hold:.3f}"
        lines.append(row)
    data = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return len(result.events)


def validate_script_keys(text: str) -> list[str]:
    """校验外部脚本键名是否合法，返回非法键名列表（供回读功能使用）。"""
    bad = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue  # 事件行至少要有 时间+键组合 两列
        for key in parts[1].split("+"):
            if key and key not in KEY_NAMES and key not in bad:
                bad.append(key)
    return bad


def parse_script(path: str) -> tuple[list, "MapResult", dict]:
    """回读时序脚本 -> (原始行列表, MapResult, 头部元数据)。

    事件行格式 `<时间>\\t<键1+键2>[\\t<保持时长>]`；键名必须在 21 键范围内。
    时间接受秒数或 分:秒.毫秒，保持文件中的数值（不归零、不截断）；
    含时长列时按“跟随音符”回读，否则按短按演奏。
    """
    from .keys import KEYS
    from .mapper import LyreEvent, MappedKey, MapResult, MapStats

    with open(path, "rb") as f:
        text = f.read().decode("utf-8")

    meta: dict = {"source": "", "instrument": "", "transpose": None,
                  "version": "v1", "has_durations": False}
    events = []
    last_t = -1.0
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            content = line[1:].strip()
            tokens = content.split()
            for ti, part in enumerate(tokens):
                if part == "genshin-lyre-script" and ti + 1 < len(tokens):
                    meta["version"] = tokens[ti + 1]
                elif part.startswith("transpose="):
                    try:
                        meta["transpose"] = int(part[10:])
                    except ValueError:
                        pass
            # source / instrument 独占一行，取完整值（可含空格）
            if content.startswith("source="):
                meta["source"] = content[len("source="):].strip()
            elif content.startswith("instrument="):
                meta["instrument"] = content[len("instrument="):].strip()
            continue
        parts = line.split("\t")
        try:
            t_str, combo = parts[0], parts[1]
            t = parse_time(t_str)
            hold = parse_time(parts[2]) if len(parts) > 2 else None
        except (ValueError, IndexError):
            raise ValueError(f"脚本第 {lineno} 行格式无效：{line[:40]!r}")
        if hold is not None and hold <= 0:
            raise ValueError(f"脚本第 {lineno} 行保持时长必须为正：{hold}")
        if hold is not None:
            meta["has_durations"] = True
        keys = []
        for name in combo.split("+"):
            k = KEYS.get(name)
            if k is None:
                raise ValueError(f"脚本第 {lineno} 行含非法键名：{name!r}")
            if name not in keys:
                keys.append(name)
        if t < last_t - 1e-9:
            raise ValueError(f"脚本第 {lineno} 行时间顺序错乱（{t} < 上一行 {last_t}）")
        last_t = t
        mk = [MappedKey(n, KEYS[n].midi_pitch, False) for n in
              sorted(keys, key=lambda n: KEYS[n].midi_pitch)]
        events.append(LyreEvent(time=t, keys=mk,
                                releases=[hold if hold is not None else TAP_HOLD] * len(mk)))

    stats = MapStats(total=sum(len(e.keys) for e in events),
                     direct=sum(len(e.keys) for e in events),
                     chord_groups=sum(1 for e in events if e.is_chord))
    usage: dict[str, int] = {}
    for e in events:
        for k in e.keys:
            usage[k.key] = usage.get(k.key, 0) + 1
    result = MapResult(events=events, stats=stats, key_usage=usage)
    return text, result, meta
