"""标准 MIDI 文件（SMF）解析：多轨合并、变速表构建、tick -> 秒换算。

支持 Format 0 / 1；检测到 Format 2 或 SMPTE 时基抛出 MidiError。
输出统一的音符事件列表与 BPM 变化表，供映射层使用。
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field

# 打击乐通道（MIDI channel 10，0 起算即 9）
PERCUSSION_CHANNEL = 9


class MidiError(Exception):
    """文件无法解析为可演奏的 MIDI。"""


@dataclass
class NoteEvent:
    """一个已配对的音符。时间为绝对秒。"""

    channel: int
    pitch: int
    velocity: int
    start: float  # 秒
    end: float    # 秒（note-off）
    track: int = 0  # 来源音轨序号（0 起算）


@dataclass
class TempoChange:
    time: float  # 秒
    bpm: float


@dataclass
class MidiSong:
    notes: list[NoteEvent]
    tempo_changes: list[TempoChange]
    duration: float          # 末个事件时间（秒）
    track_count: int         # 实际读到的音轨数
    note_on_count: int       # 原始 note-on 总数（含打击乐通道）
    filepath: str = ""
    filename: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def bpm_display(self) -> float:
        return round(self.tempo_changes[0].bpm, 1) if self.tempo_changes else 120.0


def _read_chunk(data: bytes, pos: int) -> tuple[bytes, int, int] | None:
    """返回 (chunk_id, chunk_data, 新位置)；剩余字节不足一个块头返回 None。"""
    if pos + 8 > len(data):
        return None
    cid = data[pos:pos + 4]
    size = int.from_bytes(data[pos + 4:pos + 8], "big")
    end = pos + 8 + size
    if end > len(data):
        raise MidiError("MIDI 块长度越界，文件可能被截断")
    return cid, data[pos + 8:end], end


def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
    """MIDI 变长数量（variable-length quantity）。返回 (值, 新位置)。"""
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise MidiError("变长数量越界，文件损坏")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos
    raise MidiError("变长数量超过 4 字节")


def parse_midi(data: bytes, filepath: str = "", include_drums: bool = False) -> MidiSong:
    # 头块：容忍文件前部存在少量无关字节（如 RMID 封装）
    idx = data.find(b"MThd")
    if idx < 0:
        raise MidiError("未找到 MThd 头，不是有效的 MIDI 文件")
    cid, header, pos = _read_chunk(data, idx)
    if cid != b"MThd":
        raise MidiError("MThd 头损坏")
    if len(header) < 6:
        raise MidiError("MThd 头长度不足")
    fmt = int.from_bytes(header[0:2], "big")
    ntrks = int.from_bytes(header[2:4], "big")
    division = int.from_bytes(header[4:6], "big")

    if fmt == 2:
        raise MidiError("不支持 SMF Format 2（独立多段式，罕见）")
    if division & 0x8000:
        raise MidiError("不支持 SMPTE 时基的 MIDI 文件（罕见）")
    ppq = division
    if ppq <= 0:
        raise MidiError("无效的 ticks-per-quarter 值")

    warnings: list[str] = []
    note_on_count = 0
    seen_tracks = 0

    ons: list[tuple[int, int, int, int, int]] = []   # (tick, ch, pitch, vel, track)
    offs: list[tuple[int, int, int, int]] = []       # (tick, ch, pitch, track)
    tempos: list[tuple[int, int]] = []          # (tick, us_per_quarter)

    for t_i in range(ntrks):
        chunk = _read_chunk(data, pos)
        if chunk is None:
            warnings.append("音轨块缺失，文件可能被截断")
            break
        cid, tdata, pos = chunk
        if cid != b"MTrk":
            continue  # 跳过未知块
        seen_tracks += 1
        tick = 0
        running = 0  # running status（0 表示无）
        i = 0
        n = len(tdata)
        while i < n:
            delta, i = _read_vlq(tdata, i)
            tick += delta
            if i >= n:
                raise MidiError("音轨事件越界，文件损坏")
            status = tdata[i]
            if status < 0x80:
                if not running:
                    raise MidiError("无效的 running status，文件损坏")
                status = running
            else:
                i += 1
                running = status if status < 0xF0 else 0

            if status == 0xFF:  # 元事件：i 已指向 mtype
                if i + 2 > n:
                    raise MidiError("元事件越界，文件损坏")
                mtype = tdata[i]
                mlen, j = _read_vlq(tdata, i + 1)
                if mtype == 0x51 and mlen == 3:  # Set Tempo
                    us = int.from_bytes(tdata[j:j + 3], "big")
                    if us > 0:
                        tempos.append((tick, us))
                i = j + mlen
                if i > n:
                    raise MidiError("元事件越界，文件损坏")

            elif status in (0xF0, 0xF7):  # SysEx：跳过数据
                mlen, j = _read_vlq(tdata, i)
                i = j + mlen
                if i > n:
                    raise MidiError("SysEx 事件越界，文件损坏")

            elif 0x80 <= status < 0xF0:  # 通道事件
                ch = status & 0x0F
                cmd = status & 0xF0
                nbytes = 1 if cmd in (0xC0, 0xD0) else 2
                if i + nbytes > n:
                    raise MidiError("通道事件越界，文件损坏")
                d1 = tdata[i] & 0x7F
                d2 = tdata[i + 1] & 0x7F if nbytes == 2 else 0
                i += nbytes
                if ch == PERCUSSION_CHANNEL and not include_drums:
                    continue  # 打击乐通道默认忽略
                if cmd == 0x90 and d2 > 0:
                    note_on_count += 1
                    ons.append((tick, ch, d1, d2, t_i))
                elif cmd == 0x80 or (cmd == 0x90 and d2 == 0):
                    offs.append((tick, ch, d1, t_i))
                # 其余通道事件（CC/弯音/音色等）与演奏无关，忽略

    if seen_tracks == 0:
        raise MidiError("文件中没有音轨块")

    # ---- 音符配对：同 (ch, pitch) 内，新 note-on 截断前一个未闭合音符 ----
    ons_by: dict[tuple[int, int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for tick, ch, pitch, vel, trk in ons:
        ons_by[(ch, pitch, trk)].append((tick, vel))
    offs_by: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for tick, ch, pitch, trk in offs:
        offs_by[(ch, pitch, trk)].append(tick)

    pairs: list[tuple[int, int, int, int, int, int]] = []  # (start, end, ch, pitch, vel, track)
    for (ch, pitch, trk), olist in ons_by.items():
        olist.sort()
        flist = sorted(offs_by.get((ch, pitch, trk), []))
        # 同 tick 时 off(0) 先于 on(1) 处理（同键重弹视为两个音符）
        events = [(t, 1, v) for t, v in olist] + [(t, 0, 0) for t in flist]
        events.sort()
        open_start: int | None = None
        open_vel = 0
        for tick, kind, vel in events:
            if kind == 1:
                if open_start is not None:  # 被新音符截断
                    pairs.append((open_start, tick, ch, pitch, open_vel, trk))
                open_start, open_vel = tick, vel
            else:
                if open_start is not None:
                    pairs.append((open_start, tick, ch, pitch, open_vel, trk))
                    open_start = None
        if open_start is not None:  # 兜底：无 note-off，以最后一个 off 或自身为终点
            end = flist[-1] if flist and flist[-1] > open_start else open_start
            pairs.append((open_start, max(open_start, end), ch, pitch, open_vel, trk))

    if not pairs:
        raise MidiError("未发现音符事件（可能只有打击乐轨或空谱）")

    # ---- 变速表：同 tick 去重（保留最后一个），缺失时默认 120 BPM ----
    tempos.sort()
    merged: list[tuple[int, int]] = []
    for t, us in tempos:
        if merged and merged[-1][0] == t:
            merged[-1] = (t, us)
        else:
            merged.append((t, us))
    if not merged or merged[0][0] > 0:
        merged.insert(0, (0, 500000))

    # 前缀和：cum_t[i] 时刻累计秒数 cum_s[i]，且 us_list[i] 为该段的微秒/四分音
    cum_t = [merged[0][0]]
    cum_s = [0.0]
    us_list = [merged[0][1]]
    for t, us in merged[1:]:
        dt = t - cum_t[-1]
        cum_s.append(cum_s[-1] + dt * us_list[-1] / ppq / 1e6)
        cum_t.append(t)
        us_list.append(us)

    def tick_to_sec(tick: int) -> float:
        i = bisect.bisect_right(cum_t, tick) - 1
        return cum_s[i] + (tick - cum_t[i]) * us_list[i] / ppq / 1e6

    notes = [
        NoteEvent(ch, pitch, vel, tick_to_sec(s), tick_to_sec(e), trk)
        for s, e, ch, pitch, vel, trk in pairs
    ]
    notes.sort(key=lambda x: (x.start, x.pitch))

    tempo_changes = [TempoChange(tick_to_sec(t), 60_000_000 / us) for t, us in merged]
    last_tick = max(
        [e for s, e, *_ in pairs] + [t for t, _ in merged]
    )
    duration = tick_to_sec(last_tick)

    return MidiSong(
        notes=notes,
        tempo_changes=tempo_changes,
        duration=duration,
        track_count=seen_tracks,
        note_on_count=note_on_count,
        filepath=filepath,
        filename=filepath.replace("\\", "/").rsplit("/", 1)[-1],
        warnings=warnings,
    )


def parse_midi_file(path: str) -> MidiSong:
    with open(path, "rb") as f:
        data = f.read()
    return parse_midi(data, filepath=path)
