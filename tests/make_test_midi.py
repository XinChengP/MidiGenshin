"""测试辅助：程序化构建标准 MIDI 文件字节。"""

from __future__ import annotations


def _vlq(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    parts = [value & 0x7F]
    value >>= 7
    while value:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(parts))


def note_on(tick: int, ch: int, pitch: int, vel: int = 96) -> tuple[int, bytes]:
    return (tick, bytes([0x90 | ch, pitch, vel]))


def note_off(tick: int, ch: int, pitch: int) -> tuple[int, bytes]:
    return (tick, bytes([0x80 | ch, pitch, 0]))


def note(tick: int, dur: int, ch: int, pitch: int, vel: int = 96) -> list[tuple[int, bytes]]:
    return [note_on(tick, ch, pitch, vel), note_off(tick + dur, ch, pitch)]


def note_vel0_off(tick: int, ch: int, pitch: int) -> tuple[int, bytes]:
    """velocity=0 的 note-on（等同 note-off）。"""
    return (tick, bytes([0x90 | ch, pitch, 0]))


def tempo(tick: int, bpm: float) -> tuple[int, bytes]:
    us = int(round(60_000_000 / bpm))
    return (tick, b"\xFF\x51\x03" + us.to_bytes(3, "big"))


def eot(tick: int = 0) -> tuple[int, bytes]:
    return (tick, b"\xFF\x2F\x00")


def build_midi(tracks: list[list[tuple[int, bytes]]], fmt: int = 1, ppq: int = 480) -> bytes:
    out = bytearray()
    out += b"MThd" + (6).to_bytes(4, "big") + fmt.to_bytes(2, "big") \
        + len(tracks).to_bytes(2, "big") + ppq.to_bytes(2, "big")
    for events in tracks:
        events = sorted(events, key=lambda x: x[0])
        body = bytearray()
        last = 0
        for tick, data in events:
            body += _vlq(tick - last) + data
            last = tick
        out += b"MTrk" + len(body).to_bytes(4, "big") + body
    return bytes(out)
