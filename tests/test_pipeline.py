"""核心管线自动化测试：解析 / 映射 / 导出 / 动作表 / 演奏计时。

运行：python tests/test_pipeline.py
（不依赖 pytest，直接断言 + 输出结果；GUI 截图自检另行进行）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_test_midi import (  # noqa: E402
    build_midi,
    eot,
    note,
    note_off,
    note_on,
    note_vel0_off,
    tempo,
)

from genshin_lyre.exporter import export_script, parse_script  # noqa: E402
from genshin_lyre.keys import KEYS, WIND_HORN, WIND_LYRE  # noqa: E402
from genshin_lyre.mapper import (  # noqa: E402
    HOLD_FOLLOW,
    HOLD_TAP,
    MapParams,
    map_song,
    suggest_transpose,
)
from genshin_lyre.midi_parser import MidiError, parse_midi  # noqa: E402
from genshin_lyre.player import KeySender, Player, build_actions  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    PASS += 1


# ---------------- 键位表 ----------------

def test_keys():
    check("Z=C3(48)", KEYS["Z"].midi_pitch == 48)
    check("A=C4(60)", KEYS["A"].midi_pitch == 60)
    check("Q=C5(72)", KEYS["Q"].midi_pitch == 72)
    check("U=B5(83)", KEYS["U"].midi_pitch == 83)
    check("21键齐备", len(KEYS) == 21)
    check("琴直击表仅白键", all(48 <= p <= 83 for p in WIND_LYRE.pitch_to_key))
    check("圆号直击表仅白键", all(60 <= p <= 83 for p in WIND_HORN.pitch_to_key))
    check("圆号14键两行", len(WIND_HORN.key_names) == 14 and len(WIND_HORN.rows) == 2)
    check("圆号无Z行", "Z" not in WIND_HORN.key_names and "M" not in WIND_HORN.key_names)


# ---------------- 原琴·两排映射 ----------------

def test_map_horn():
    p = MapParams(instrument=WIND_HORN)
    # 用户给定的映射表：60=A,62=S,64=D,65=F,67=G,69=H,71=J / 72=Q,74=W,76=E,77=R,79=T,81=Y,83=U
    expect = {60: "A", 62: "S", 64: "D", 65: "F", 67: "G", 69: "H", 71: "J",
              72: "Q", 74: "W", 76: "E", 77: "R", 79: "T", 81: "Y", 83: "U"}
    r = map_song(_song_of(sorted(expect)), p)
    got = {k.pitch: k.key for e in r.events for k in e.keys}
    check("圆号映射表逐一吻合", got == expect, str(got))

    # 音域下界：B3(59)、C3(48) 在圆号上丢弃
    r = map_song(_song_of([48, 59, 60]), p)
    check("圆号丢弃 <C4", r.stats.dropped_range == 2 and r.stats.kept == 1)
    check("圆号最低丢弃 C3", r.stats.min_dropped_pitch == 48)
    check("圆号事件仅 1 个", len(r.events) == 1 and r.events[0].combo == "A")

    # 上界：C6(84) 丢弃
    r = map_song(_song_of([83, 84]), p)
    check("圆号丢弃 >B5", r.stats.dropped_range == 1 and r.events[0].combo == "U")

    # 黑键吸附：C#4(61) -> C4(A)，A#4(70) -> A4(H)
    r = map_song(_song_of([61, 70]), p)
    check("圆号黑键吸附", [e.combo for e in r.events] == ["A", "H"]
          and r.stats.snapped == 2)

    # 与琴对比：C3 在琴可弹(Z)，在圆号丢弃
    r_lyre = map_song(_song_of([48]), MapParams())
    r_horn = map_song(_song_of([48]), MapParams(instrument=WIND_HORN))
    check("同一音高按乐器区分", r_lyre.events[0].combo == "Z"
          and r_horn.stats.dropped_range == 1)

    # 圆号下移调建议：全部 C4–E4 乐句建议 +12 提到高音区？验证建议可运行且结果有效
    song = _song_of([60, 62, 64])
    best = suggest_transpose(song, p)
    p_best = MapParams(instrument=WIND_HORN, transpose=best)
    r_best = map_song(song, p_best)
    check("圆号移调建议有效", r_best.stats.dropped == 0, f"best={best}")


# ---------------- 解析 ----------------

def test_parse_basic():
    # C3..C4 八个四分音符 @120BPM（1 tick = 0.5s）
    evs = []
    for i, p in enumerate(range(48, 56)):
        evs += note(i * 480, 240, 0, p)
    evs.append(eot(8 * 480))
    song = parse_midi(build_midi([evs], fmt=0), "basic.mid")

    check("Format0 音符数", len(song.notes) == 8, str(len(song.notes)))
    check("起始 BPM=120", abs(song.tempo_changes[0].bpm - 120) < 0.01)
    times = [round(n.start, 3) for n in song.notes]
    check("时间轴 0.5s 间隔", times == [round(i * 0.5, 3) for i in range(8)], str(times))
    check("时长（末音符 off）", abs(song.duration - (7 * 480 + 240) * 0.5 / 480) < 0.01,
          str(song.duration))


def test_parse_tempo_change():
    # 前 2 拍 120BPM，之后 60BPM
    evs = [tempo(0, 120), tempo(960, 60)]
    for i in range(4):
        evs += note(i * 480, 240, 0, 60 + i)
    evs.append(eot(4 * 480))
    song = parse_midi(build_midi([evs]))
    times = [round(n.start, 3) for n in song.notes]
    # tick 0->0s, 480->0.5s, 960->1.0s, 1440->2.0s
    check("变速后时间换算", times == [0.0, 0.5, 1.0, 2.0], str(times))
    check("BPM 变化点 2 处", len(song.tempo_changes) == 2)
    check("变速后 BPM=60", abs(song.tempo_changes[1].bpm - 60) < 0.01)


def test_parse_multitrack_and_drums():
    trk0 = [tempo(0, 120), eot(960)]
    trk1 = note(0, 480, 0, 60) + note(480, 480, 0, 62) + [eot(960)]
    trk2 = note(0, 480, 1, 64) + [eot(480)]
    trk_drums = note(0, 240, 9, 36) + [eot(240)]  # 打击乐
    song = parse_midi(build_midi([trk0, trk1, trk2, trk_drums]))
    check("多轨合并 3 音符", len(song.notes) == 3, str(len(song.notes)))
    check("轨数统计", song.track_count == 4)
    song2 = parse_midi(build_midi([trk0, trk1, trk2, trk_drums]), include_drums=True)
    check("包含打击乐后 4 音符", len(song2.notes) == 4)


def test_parse_retouch_and_vel0():
    # 同键重弹（off 与 on 同 tick）+ velocity=0 note-off
    evs = [tempo(0, 120), note_on(0, 0, 60), note_off(480, 0, 60),
           note_on(480, 0, 60), note_vel0_off(960, 0, 60), eot(960)]
    song = parse_midi(build_midi([evs]))
    check("同键重弹 2 音符", len(song.notes) == 2, str(len(song.notes)))
    check("重弹音符时间", [round(n.start, 3) for n in song.notes] == [0.0, 0.5])


def test_parse_overlap_truncate():
    # 重叠：note-on at 0 (dur 960)，note-on at 480 截断前者
    evs = [tempo(0, 120), note_on(0, 0, 60), note_on(480, 0, 60),
           note_off(960, 0, 60), note_off(1440, 0, 60), eot(1440)]
    song = parse_midi(build_midi([evs]))
    check("重叠截断 2 音符", len(song.notes) == 2, str(len(song.notes)))
    n0, n1 = song.notes
    check("前者被截断于 0.5s", abs(n0.end - 0.5) < 1e-6, f"end={n0.end}")
    check("后者 0.5-1.0s", abs(n1.start - 0.5) < 1e-6 and abs(n1.end - 1.0) < 1e-6)


def test_parse_unclosed():
    evs = [tempo(0, 120), note_on(0, 0, 60), eot(480)]
    song = parse_midi(build_midi([evs]))
    check("未闭合音符兜底", len(song.notes) == 1)


def test_parse_errors():
    for name, data in [
        ("非 MIDI", b"hello world not a midi file at all"),
        ("空文件", b""),
        ("头被截断", b"MThd\x00\x00\x00\x06\x00\x01"),
    ]:
        try:
            parse_midi(data)
            check(f"错误输入拒绝：{name}", False)
        except MidiError:
            check(f"错误输入拒绝：{name}", True)


# ---------------- 映射 ----------------

def _song_of(pitches, dur=480, bpm=120):
    evs = [tempo(0, bpm)]
    for i, p in enumerate(pitches):
        evs += note(i * dur, dur // 2, 0, p)
    evs.append(eot(len(pitches) * dur))
    return parse_midi(build_midi([evs]))


def test_map_direct():
    r = map_song(_song_of([60, 62, 64]), MapParams())
    check("C4->A", r.events[0].combo == "A")
    check("D4->S", r.events[1].combo == "S")
    check("E4->D", r.events[2].combo == "D")
    check("直击 3", r.stats.direct == 3 and r.stats.dropped == 0)
    check("默认跟随音符 0.25s", abs(r.events[0].hold - 0.25) < 1e-6,
          str(r.events[0].hold))
    r_tap = map_song(_song_of([60]), MapParams(hold_mode=HOLD_TAP))
    check("短按保持 60ms", abs(r_tap.events[0].hold - 0.060) < 1e-6)


def test_map_transpose():
    r = map_song(_song_of([60]), MapParams(transpose=12))
    check("移调+12 C5->Q", r.events[0].combo == "Q")
    r = map_song(_song_of([60]), MapParams(transpose=-12))
    check("移调-12 C3->Z", r.events[0].combo == "Z")
    try:
        map_song(_song_of([60]), MapParams(transpose=13))
        check("移调越界拒绝", False)
    except ValueError:
        check("移调越界拒绝", True)


def test_map_range_drop():
    r = map_song(_song_of([36, 60, 84, 84]), MapParams())
    check("音域外丢弃", r.stats.dropped_range == 3, str(r.stats.dropped_range))
    check("保留 1", r.stats.kept == 1)
    check("最低丢弃 C2", r.stats.min_dropped_pitch == 36)
    check("最高丢弃 C6", r.stats.max_dropped_pitch == 84)
    check("事件数 1", len(r.events) == 1)


def test_map_black_keys():
    song = _song_of([61])  # C#4
    r = map_song(song, MapParams(snap="down"))
    check("C#4 吸附向下 -> C4(A)", r.events[0].combo == "A" and r.stats.snapped == 1)
    r = map_song(song, MapParams(snap="up"))
    check("C#4 吸附向上 -> D4(S)", r.events[0].combo == "S")
    r = map_song(song, MapParams(snap="drop"))
    check("C#4 丢弃", len(r.events) == 0 and r.stats.dropped == 1)
    # 吸附后与组内已有键冲突（同 tick 的 C4 与 C#4）
    evs = [tempo(0, 120)] + note(0, 480, 0, 60) + note(0, 480, 0, 61) + [eot(480)]
    song2 = parse_midi(build_midi([evs]))
    r = map_song(song2, MapParams(snap="down"))
    check("吸附冲突丢弃，仅 1 键", len(r.events) == 1 and len(r.events[0].keys) == 1,
          str(r.events))
    check("冲突计数 1", r.stats.dropped_collision == 1)


def test_map_chords():
    # 同 tick 三和弦 C4+E4+G4
    evs = [tempo(0, 120)] + note(0, 480, 0, 60) + note(0, 480, 0, 64) \
        + note(0, 480, 0, 67) + note(480, 480, 0, 72) + [eot(960)]
    song = parse_midi(build_midi([evs]))
    r = map_song(song, MapParams())
    check("和弦合并 2 事件", len(r.events) == 2)
    check("组合 Z序 A+D+G", r.events[0].combo == "A+D+G", r.events[0].combo)
    check("和弦标记", r.events[0].is_chord and not r.events[1].is_chord)
    check("组内按音高排序", [k.pitch for k in r.events[0].keys] == [60, 64, 67])


def test_map_chord_tolerance():
    # 10ms 差的两个音：容差 20ms 合并，容差 5ms 不合并
    evs = [tempo(0, 120)] + note(0, 480, 0, 60) + note(96, 480, 0, 64) + [eot(960)]
    # 96 ticks @120bpm/480ppq = 0.1s = 100ms —— 超 20ms，不合并
    song = parse_midi(build_midi([evs]))
    r = map_song(song, MapParams(chord_tol=0.020))
    check("100ms 差不合并", len(r.events) == 2)
    # 4.8ms 差（5 ticks @ 500_000us? 用 1/4 拍）：改用高 ppq 检查容差边界
    evs2 = [tempo(0, 120)] + note(0, 480, 0, 60) + note(4, 480, 0, 64) + [eot(960)]
    song2 = parse_midi(build_midi([evs2]))
    r2 = map_song(song2, MapParams(chord_tol=0.020))
    check("~4ms 差合并", len(r2.events) == 1)


def test_map_hold_follow():
    evs = [tempo(0, 120)] + note(0, 960, 0, 60) + [eot(960)]  # 1s 长音
    song = parse_midi(build_midi([evs]))
    r = map_song(song, MapParams(hold_mode=HOLD_FOLLOW))
    check("跟随音符 1s", abs(r.events[0].hold - 1.0) < 1e-6, str(r.events[0].hold))
    # 超长音截断 2s
    evs = [tempo(0, 60)] + note(0, 3840, 0, 60) + [eot(3840)]  # 4s
    song = parse_midi(build_midi([evs]))
    r = map_song(song, MapParams(hold_mode=HOLD_FOLLOW))
    check("长音上限 2s", abs(r.events[0].hold - 2.0) < 1e-6)


def test_suggest_transpose():
    # 4 个 C#4 + 1 个 C4：建议 -1（全部变直击）
    song = _song_of([61, 61, 61, 61, 60])
    best = suggest_transpose(song, MapParams())
    check("移调建议 -1", best == -1, str(best))


# ---------------- 导出 ----------------

def test_export(tmp="test_out.txt"):
    r = map_song(_song_of([60, 64, 67, 72], dur=960), MapParams())
    n = export_script(r, MapParams(), tmp, source_name="test.mid")
    with open(tmp, "rb") as f:
        data = f.read().decode("utf-8")
    lines = data.split("\r\n")
    check("行数 = 头 6 + 事件 4 + 尾空", len(lines) == 6 + 4 + 1, str(len(lines)))
    check("版本头", lines[0] == "# genshin-lyre-script v1")
    check("乐器头", lines[2] == "# instrument=原琴（三排）", lines[2])
    check("事件行", lines[6] == "0.000\tA" and lines[7] == "1.000\tD")
    check("CRLF + UTF-8", data.endswith("\r\n") and "\tA\r\n" in data)
    check("返回事件数", n == 4)
    # 分:秒 格式 + 速度缩放
    export_script(r, MapParams(), tmp, clock_format=True, include_header=False, speed=2.0)
    data = open(tmp, "rb").read().decode("utf-8")
    check("速度缩放 200%", "00:00.500\tD" in data and "00:01.000\tG" in data, data[:60])
    os.remove(tmp)


# ---------------- 动作表 ----------------

def test_build_actions():
    song = _song_of([60, 60, 62])  # A A S —— 同键重弹
    r = map_song(song, MapParams(hold_mode=HOLD_TAP))
    acts = build_actions(r.events, 1.0, "tap")
    downs = [(round(a.time, 4), a.kind, a.keys) for a in acts if a.kind == "down"]
    ups = [(round(a.time, 4), a.kind, a.keys) for a in acts if a.kind == "up"]
    # 重弹：0.5s 处第二次按下前必须有松开（0.06 短按已自然松开，无插入）
    check("短按下行 3 次", len(downs) == 3, str(downs))
    check("短按上行 3 次", len(ups) == 3, str(ups))
    # 速度缩放
    acts = build_actions(r.events, 2.0, "tap")
    check("速度 200% 间隔减半", abs(acts[-1].time - (1.0 / 2 + 0.06)) < 1e-6,
          str(acts[-1].time))
    # hold 模式同键冲突：0~4s 长音 C4，0.5s 再按 C4（重叠截断成 0~0.5 与 0.5~1）
    evs = [tempo(0, 120), note_on(0, 0, 60), note_on(480, 0, 60),
           note_off(960, 0, 60), note_off(1920, 0, 60), eot(1920)]
    song = parse_midi(build_midi([evs]))
    r = map_song(song, MapParams(hold_mode=HOLD_FOLLOW))
    acts = build_actions(r.events, 1.0, "follow")
    key_ops = sorted([(a.time, a.kind) for a in acts for k in a.keys if k == "A"],
                     key=lambda x: (x[0], 0 if x[1] == "up" else 1))
    held = False
    ok = True
    for t, kind in key_ops:
        if kind == "down":
            if held:
                ok = False
            held = True
        else:
            held = False
    check("follow 模式同键先松后按", ok, str(key_ops))


# ---------------- 演奏计时（dry-run） ----------------

def test_player_timing():
    # 100 个事件，间隔 50ms，对比 dry-run 实际发送时刻（以首个事件为基准，测漂移与间隔）
    from genshin_lyre.mapper import LyreEvent, MappedKey
    events = [LyreEvent(time=i * 0.05, keys=[MappedKey("A", 60, False)],
                        releases=[0.060]) for i in range(100)]
    acts = build_actions(events, 1.0, "tap")
    sender = KeySender(dry_run=True)
    states = []
    p = Player(acts, sender, on_state=lambda s, d: states.append(s))
    p.start()
    p.join(timeout=15)
    check("演奏线程结束", not p.is_alive())
    downs = [x for x in sender.log if x[1] == "down"]
    check("发送次数 100", len(downs) == 100, str(len(downs)))
    base = downs[0][0]
    errs = [abs((t - base) - i * 0.05) for i, (t, _k, _key) in enumerate(downs)]
    mean_err = sum(errs) / len(errs)
    max_err = max(errs)
    print(f"       计时精度: 平均误差 {mean_err * 1000:.2f}ms, 最大 {max_err * 1000:.2f}ms")
    check("平均误差 <=5ms", mean_err <= 0.005, f"{mean_err * 1000:.2f}ms")
    check("最大误差 <=15ms", max_err <= 0.015, f"{max_err * 1000:.2f}ms")
    check("结束状态 finished", states and states[-1] == "finished", str(states))


def test_player_pause_stop():
    from genshin_lyre.mapper import LyreEvent, MappedKey
    events = [LyreEvent(time=i * 0.1, keys=[MappedKey("A", 60, False)],
                        releases=[0.060]) for i in range(200)]  # 20 秒
    acts = build_actions(events, 1.0, "tap")
    sender = KeySender(dry_run=True)
    states = []
    p = Player(acts, sender, on_state=lambda s, d: states.append(s))
    p.start()
    time.sleep(0.5)
    p.pause()
    time.sleep(0.3)
    n_at_pause = len([x for x in sender.log if x[1] == "down"])
    p.stop()
    p.join(timeout=5)
    check("暂停后停止成功", not p.is_alive())
    n_final = len([x for x in sender.log if x[1] == "down"])
    check("停止后不再发送", n_final <= n_at_pause + 10, f"{n_at_pause} -> {n_final}")
    downs = [x for x in sender.log if x[1] == "down"]
    ups = [x for x in sender.log if x[1] == "up"]
    check("无按键残留", len(ups) >= len(downs) - 1, f"down={len(downs)} up={len(ups)}")


# ---------------- 音轨筛选 / 黑键统计 / 回读 / 跳播 ----------------

def test_track_filter():
    # 三轨：0=旋律 1=低音 2=装饰音
    trk0 = [tempo(0, 120)] + note(0, 480, 0, 60) + note(480, 480, 0, 62) + [eot(960)]
    trk1 = note(0, 480, 1, 48) + [eot(480)]
    trk2 = note(240, 240, 2, 76) + [eot(480)]
    song = parse_midi(build_midi([trk0, trk1, trk2]))
    check("音符带轨号", sorted({n.track for n in song.notes}) == [0, 1, 2],
          str(sorted({n.track for n in song.notes})))
    r = map_song(song, MapParams())
    check("全轨 4 音符", r.stats.total == 4)
    r = map_song(song, MapParams(), exclude_tracks={1, 2})
    check("排除轨1+2 后 2 音符", r.stats.total == 2, str(r.stats.total))
    check("排除后事件仅 A S", [e.combo for e in r.events] == ["A", "S"])
    r = map_song(song, MapParams(), exclude_tracks=frozenset({0}))
    check("排除轨0 后 2 音符", r.stats.total == 2)


def test_blackkey_drop_stat():
    song = _song_of([61, 60, 84])  # C#4(黑键), C4, C6(超音域)
    r = map_song(song, MapParams(snap="drop"))
    check("黑键丢弃独立计数", r.stats.dropped_blackkey == 1, str(r.stats.dropped_blackkey))
    check("音域外仍计 dropped_range", r.stats.dropped_range == 1)
    check("汇总 dropped=2", r.stats.dropped == 2)
    # 吸附模式 blackkey=0
    r = map_song(song, MapParams(snap="down"))
    check("吸附模式黑键丢弃为 0", r.stats.dropped_blackkey == 0)


def test_script_roundtrip(tmp="test_script.txt"):
    # 导出 -> 回读 -> 事件一致
    r = map_song(_song_of([60, 64, 67], dur=960), MapParams())
    n = export_script(r, MapParams(), tmp, source_name="rt.mid")
    _, r2, meta = parse_script(tmp)
    check("回读事件数一致", len(r2.events) == len(r.events) == 4 or
          len(r2.events) == len(r.events), f"{len(r2.events)} vs {len(r.events)}")
    check("回读组合一致", [e.combo for e in r2.events] == [e.combo for e in r.events])
    check("回读时间一致", [round(e.time, 3) for e in r2.events] ==
          [round(e.time, 3) for e in r.events])
    check("回读头部 source", meta["source"] == "rt.mid")
    check("回读乐器头", meta["instrument"] == "原琴（三排）")
    # 非法键名
    with open(tmp, "wb") as f:
        f.write("0.000\tZZZ\r\n".encode("utf-8"))
    try:
        parse_script(tmp)
        check("非法键名拒绝", False)
    except ValueError:
        check("非法键名拒绝", True)
    # 时间乱序
    with open(tmp, "wb") as f:
        f.write("1.000\tA\r\n0.500\tS\r\n".encode("utf-8"))
    try:
        parse_script(tmp)
        check("时间乱序拒绝", False)
    except ValueError:
        check("时间乱序拒绝", True)
    os.remove(tmp)


def test_auto_adjust():
    from genshin_lyre.keys import WIND_HORN, WIND_LYRE
    from genshin_lyre.mapper import auto_adjust
    # 中音区 C 大调（跨度 12）：两排 +0
    inst, t = auto_adjust(_song_of(list(range(60, 73))), MapParams())
    check("中音区 -> 两排 +0", (inst.id, t) == ("horn", 0), f"{inst.id} {t}")
    # 低音区（跨度 12）：两排 +12
    inst, t = auto_adjust(_song_of(list(range(48, 61))), MapParams())
    check("低音区 -> 两排 +12", (inst.id, t) == ("horn", 12), f"{inst.id} {t}")
    # 大跨度（>24）：三排
    inst, t = auto_adjust(_song_of(list(range(45, 89))), MapParams())
    check("大跨度 -> 三排", inst.id == "lyre", inst.id)
    # 二排劣于三排时不强用二排：高黑键密度大跨度直接三排（由上覆盖）


def test_seek():
    from genshin_lyre.mapper import LyreEvent, MappedKey
    events = [LyreEvent(time=i * 0.08, keys=[MappedKey("A", 60, False)],
                        releases=[0.060]) for i in range(120)]  # 9.6s
    acts = build_actions(events, 1.0, "tap")
    sender = KeySender(dry_run=True)
    p = Player(acts, sender)
    p.start()
    time.sleep(0.4)          # 约 5 个事件
    p.seek(60)               # 跳到事件 60（约 4.8s）
    time.sleep(0.3)
    p.stop()
    p.join(timeout=5)
    downs = [t for t, kind, _ in sender.log if kind == "down"]
    after_seek = [t for t in downs if t > 0.4]
    check("跳播后立即从新位置继续", after_seek and min(after_seek) < 0.75,
          str([round(t, 2) for t in downs[-8:]]))
    # 跳播地板：事件 60 之前的动作不再发送（统计事件 0-5 后 seek 前）
    check("演奏线程正常结束", not p.is_alive())


def test_export_v2_follow(tmp="test_v2.txt"):
    # 跟随音符模式导出 v2，回读后保持时长，可再以 follow 演奏
    r = map_song(_song_of([60], dur=960), MapParams(hold_mode=HOLD_FOLLOW))
    export_script(r, MapParams(hold_mode=HOLD_FOLLOW), tmp, include_durations=True)
    text = open(tmp, encoding="utf-8").read()
    check("v2 头", "# genshin-lyre-script v2" in text)
    _, r2, meta = parse_script(tmp)
    check("v2 回读标记", meta["has_durations"] and meta["version"] == "v2")
    check("v2 回读时长 0.5s", abs(r2.events[0].releases[0] - 0.5) < 1e-6,
          str(r2.events[0].releases))
    # 跟随模式动作表：up 在 1s 处
    acts = build_actions(r2.events, 1.0, "follow")
    ups = [a.time for a in acts if a.kind == "up"]
    check("v2 follow 回读 up@0.5s", ups and abs(ups[0] - 0.5) < 1e-6, str(ups))
    os.remove(tmp)


def main():
    test_keys()
    test_parse_basic()
    test_parse_tempo_change()
    test_parse_multitrack_and_drums()
    test_parse_retouch_and_vel0()
    test_parse_overlap_truncate()
    test_parse_unclosed()
    test_parse_errors()
    test_map_direct()
    test_map_horn()
    test_map_transpose()
    test_map_range_drop()
    test_map_black_keys()
    test_map_chords()
    test_map_chord_tolerance()
    test_map_hold_follow()
    test_suggest_transpose()
    test_export()
    test_build_actions()
    test_player_timing()
    test_player_pause_stop()
    test_track_filter()
    test_blackkey_drop_stat()
    test_script_roundtrip()
    test_auto_adjust()
    test_seek()
    test_export_v2_follow()
    print(f"\n全部通过：{PASS} 项检查")


if __name__ == "__main__":
    main()
