"""乐器键位定义与 MIDI 音高映射。

支持两种乐器：
- 风物之诗琴：21 键三行（低 Z 行 / 中 A 行 / 高 Q 行），音域 C3–B5
- 晚风圆号：  14 键两行（中 A 行 / 高 Q 行），音域 C4–B5，无低音行

按键的虚拟键码 / 扫描码按字符全局共享（两乐器的同名键物理键相同）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

ROW_LOW = ["Z", "X", "C", "V", "B", "N", "M"]
ROW_MID = ["A", "S", "D", "F", "G", "H", "J"]
ROW_HIGH = ["Q", "W", "E", "R", "T", "Y", "U"]

# 行内序号 -> 白键音级（相对 C 的半音数）
_SEMITONES = (0, 2, 4, 5, 7, 9, 11)
_BLACK_SEMITONES = {1, 3, 6, 8, 10}

_VK = {c: ord(c) for c in "ZXCVBNMASDFGHJQWERTYU"}
_SC = {  # Set 1 (PS/2) make code，即 KEYEVENTF_SCANCODE 使用的扫描码
    "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13, "T": 0x14, "Y": 0x15, "U": 0x16,
    "A": 0x1E, "S": 0x1F, "D": 0x20, "F": 0x21, "G": 0x22, "H": 0x23, "J": 0x24,
    "Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F, "B": 0x30, "N": 0x31, "M": 0x32,
}


@dataclass(frozen=True)
class LyreKey:
    """单个按键的物理属性与其在标准 21 键布局中的音高。"""

    name: str
    vk: int
    scan: int
    midi_pitch: int  # 风物之诗琴布局下的音高（C3–B5）

    @property
    def note_name(self) -> str:
        return f"{NOTE_NAMES[self.midi_pitch % 12]}{self.midi_pitch // 12 - 1}"


# 全部按键的物理属性表（键名 -> vk/scan/pitch）
KEYS: dict[str, LyreKey] = {}
for _row, _oct in ((ROW_LOW, 3), (ROW_MID, 4), (ROW_HIGH, 5)):
    for _i, _name in enumerate(_row):
        KEYS[_name] = LyreKey(_name, _VK[_name], _SC[_name],
                              12 * (_oct + 1) + _SEMITONES[_i])

KEY_NAMES: list[str] = ROW_LOW + ROW_MID + ROW_HIGH


@dataclass(frozen=True, eq=False)
class Instrument:
    """一种乐器的可演奏键位集。"""

    id: str
    name: str
    rows: tuple[tuple[str, ...], ...]          # 每行键名，低音行在前
    pitch_range: tuple[int, int]               # 可演奏 MIDI 音高范围（含端点）
    pitch_to_key: dict[int, str] = field(default_factory=dict, compare=False)
    snap_down: dict[int, str] = field(default_factory=dict, compare=False)  # 黑键 -> 低半音白键
    snap_up: dict[int, str] = field(default_factory=dict, compare=False)    # 黑键 -> 高半音白键

    @property
    def key_names(self) -> list[str]:
        return [k for row in self.rows for k in row]

    @property
    def pitch_min(self) -> int:
        return self.pitch_range[0]

    @property
    def pitch_max(self) -> int:
        return self.pitch_range[1]

    @property
    def row_labels(self) -> tuple[str, ...]:
        if len(self.rows) == 3:
            return ("低音", "中音", "高音")
        if len(self.rows) == 2:
            return ("中音", "高音")
        return tuple(f"第{i+1}行" for i in range(len(self.rows)))


def _build_instrument(inst_id: str, name: str,
                      rows_spec: tuple[tuple[list[str], int], ...]) -> Instrument:
    """rows_spec: (行键名, 八度号)；行内 7 键对应 C 大调 do–si。"""
    pitch_to_key: dict[int, str] = {}
    for row_keys, octave in rows_spec:
        for i, key_name in enumerate(row_keys):
            pitch_to_key[12 * (octave + 1) + _SEMITONES[i]] = key_name
    lo, hi = min(pitch_to_key), max(pitch_to_key)
    blacks = [p for p in range(lo, hi + 1) if p % 12 in _BLACK_SEMITONES]
    snap_down = {p: pitch_to_key[p - 1] for p in blacks}
    snap_up = {p: pitch_to_key[p + 1] for p in blacks}
    rows = tuple(tuple(r) for r, _ in rows_spec)
    return Instrument(inst_id, name, rows, (lo, hi), pitch_to_key, snap_down, snap_up)


WIND_LYRE = _build_instrument(
    "lyre", "风物之诗琴",
    ((ROW_LOW, 3), (ROW_MID, 4), (ROW_HIGH, 5)),
)
WIND_HORN = _build_instrument(
    "horn", "晚风圆号",
    # 晚风圆号：仅两行，无低音行；中音行 C4 起
    ((ROW_MID, 4), (ROW_HIGH, 5)),
)
INSTRUMENTS: dict[str, Instrument] = {"lyre": WIND_LYRE, "horn": WIND_HORN}


def pitch_name(pitch: int) -> str:
    """MIDI 音高 -> 'C#4' 形式音名（C4=60）。"""
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def is_black_key(pitch: int) -> bool:
    return pitch % 12 in _BLACK_SEMITONES
