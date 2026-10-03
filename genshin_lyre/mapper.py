"""音符映射：移调 -> 音域过滤 -> 黑键处理 -> 和弦合并 -> 按键事件。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .keys import (
    Instrument,
    WIND_LYRE,
    is_black_key,
    pitch_name,
)
from .midi_parser import MidiSong

TAP_HOLD = 0.060      # 短按保持 60ms
MAX_HOLD = 2.0        # 跟随音符模式的最大保持
MIN_HOLD = 0.060      # 任何模式下的最小保持

SNAP_DOWN = "down"
SNAP_UP = "up"
SNAP_DROP = "drop"

HOLD_TAP = "tap"
HOLD_FOLLOW = "follow"


@dataclass(frozen=True)
class MapParams:
    instrument: Instrument = WIND_LYRE
    transpose: int = 0          # 半音，-12..+12
    snap: str = SNAP_DOWN       # down / up / drop
    chord_tol: float = 0.020    # 和弦合并容差（秒）
    hold_mode: str = HOLD_TAP   # tap / follow

    def validate(self) -> "MapParams":
        if self.instrument is None:
            raise ValueError("必须指定乐器")
        if not -12 <= self.transpose <= 12:
            raise ValueError("移调必须在 -12 ~ +12 之间")
        if not 0 <= self.chord_tol <= 0.050:
            raise ValueError("和弦容差必须在 0 ~ 50ms 之间")
        return self


@dataclass
class MappedKey:
    key: str            # 键名，如 "A"
    pitch: int          # 移调后的 MIDI 音高
    snapped: bool       # 是否由黑键吸附而来


@dataclass
class LyreEvent:
    """一个按键事件：同一时刻按下的按键组合。"""

    time: float                        # 相对首个音符的秒数
    keys: list[MappedKey]              # 已按音高从低到高排序
    releases: list[float]              # 与 keys 对齐的松开时刻偏移（秒）
    dropped_collision: int = 0         # 本组内因重键冲突被丢弃的音符数

    @property
    def is_chord(self) -> bool:
        return len(self.keys) > 1

    @property
    def combo(self) -> str:
        return "+".join(k.key for k in self.keys)

    @property
    def hold(self) -> float:
        return max(self.releases) if self.releases else TAP_HOLD


@dataclass
class MapStats:
    total: int = 0            # 参与映射的音符数（非打击乐）
    direct: int = 0           # 白键直击
    snapped: int = 0          # 黑键吸附
    dropped_range: int = 0    # 音域外丢弃
    dropped_blackkey: int = 0   # 黑键因策略为"直接丢弃"而丢弃
    dropped_collision: int = 0  # 同和弦重键丢弃
    chord_groups: int = 0
    min_dropped_pitch: int | None = None
    max_dropped_pitch: int | None = None
    first_note_time: float = 0.0

    @property
    def kept(self) -> int:
        return self.direct + self.snapped

    @property
    def dropped(self) -> int:
        return self.dropped_range + self.dropped_blackkey + self.dropped_collision


@dataclass
class MapResult:
    events: list[LyreEvent]
    stats: MapStats
    key_usage: dict[str, int] = field(default_factory=dict)


def _map_pitch(pitch: int, params: MapParams, stats: MapStats) -> str | None:
    """单个音高 -> 键名；无法演奏返回 None（已计入统计）。"""
    inst = params.instrument
    if pitch < inst.pitch_min or pitch > inst.pitch_max:
        stats.dropped_range += 1
        if stats.min_dropped_pitch is None or pitch < stats.min_dropped_pitch:
            stats.min_dropped_pitch = pitch
        if stats.max_dropped_pitch is None or pitch > stats.max_dropped_pitch:
            stats.max_dropped_pitch = pitch
        return None
    if not is_black_key(pitch):
        stats.direct += 1
        return inst.pitch_to_key[pitch]
    if params.snap == SNAP_DROP:
        stats.dropped_blackkey += 1
        return None
    snap_table = inst.snap_down if params.snap == SNAP_DOWN else inst.snap_up
    key = snap_table.get(pitch)
    if key is None:
        stats.dropped_range += 1
        return None
    stats.snapped += 1
    return key


def map_song(song: MidiSong, params: MapParams,
             exclude_tracks: frozenset[int] | set[int] | None = None) -> MapResult:
    params = params.validate()
    notes = song.notes
    if exclude_tracks:
        notes = [n for n in notes if n.track not in exclude_tracks]
    stats = MapStats(total=len(notes))
    stats.first_note_time = min((n.start for n in notes), default=0.0)

    # 1) 逐音符映射到键，携带（时间, 移调后音高, 键, 结束时间）
    mapped: list[tuple[float, int, str, float]] = []
    for note in notes:
        pitch = note.pitch + params.transpose
        key = _map_pitch(pitch, params, stats)
        if key is not None:
            mapped.append((note.start - stats.first_note_time, pitch, key,
                           max(note.end - stats.first_note_time, note.start - stats.first_note_time)))
    mapped.sort(key=lambda x: x[0])

    # 2) 和弦合并：与组首音符起始差 <= 容差 归入同组
    groups: list[list[tuple[float, int, str, float]]] = []
    for item in mapped:
        if groups and item[0] - groups[-1][0][0] <= params.chord_tol:
            groups[-1].append(item)
        else:
            groups.append([item])

    # 3) 组内去重（吸附后同键冲突则丢弃后者）、排序、计算保持时长
    events: list[LyreEvent] = []
    key_usage: dict[str, int] = {}
    for group in groups:
        seen: set[str] = set()
        items: list[tuple[MappedKey, float]] = []  # (键, 松开偏移)，随音高一起排序
        collision = 0
        for t, pitch, key, end in group:
            if key in seen:
                collision += 1
                continue
            seen.add(key)
            if params.hold_mode == HOLD_FOLLOW:
                release = min(max(end - t, MIN_HOLD), MAX_HOLD)
            else:
                release = TAP_HOLD
            items.append((MappedKey(key, pitch, snapped=is_black_key(pitch)), release))
        items.sort(key=lambda pair: pair[0].pitch)
        keys = [k for k, _ in items]
        releases = [r for _, r in items]
        for k in keys:
            key_usage[k.key] = key_usage.get(k.key, 0) + 1
        events.append(LyreEvent(time=group[0][0], keys=keys, releases=releases,
                                dropped_collision=collision))
        stats.dropped_collision += collision

    stats.chord_groups = sum(1 for e in events if e.is_chord)
    return MapResult(events=events, stats=stats, key_usage=key_usage)


def suggest_transpose(song: MidiSong, params: MapParams) -> int:
    """枚举 -12..+12：丢弃最少优先，其次直击最多，最后移调幅度小者优先。"""
    best = 0
    best_score = (-1, -1, 1)  # (丢弃数升序, 直击数降序, 幅度升序)
    for t in range(-12, 13):
        try:
            p = MapParams(instrument=params.instrument, transpose=t,
                          snap=params.snap, chord_tol=params.chord_tol,
                          hold_mode=params.hold_mode)
            result = map_song(song, p)
        except ValueError:
            continue
        score = (-result.stats.dropped, result.stats.direct, -abs(t))
        if score > best_score:
            best_score = score
            best = t
    return best


def dropped_summary(result: MapResult) -> str:
    s = result.stats
    parts = [f"音域外 {s.dropped_range}"]
    if s.dropped_blackkey:
        parts.append(f"黑键丢弃 {s.dropped_blackkey}")
    parts.append(f"重键冲突 {s.dropped_collision}")
    if s.min_dropped_pitch is not None:
        parts.append(f"最低丢弃 {pitch_name(s.min_dropped_pitch)}")
    if s.max_dropped_pitch is not None and s.max_dropped_pitch != s.min_dropped_pitch:
        parts.append(f"最高丢弃 {pitch_name(s.max_dropped_pitch)}")
    return " · ".join(parts)
