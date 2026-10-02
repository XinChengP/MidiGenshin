"""生成演示用 MIDI 文件（examples/demo.mid）：多轨 + 变速 + 黑键 + 超音域音符。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_test_midi import build_midi, eot, note, note_off, note_on, tempo


def main():
    # 轨 0：曲速 100 -> 116（第 8 拍）
    trk0 = [tempo(0, 100), tempo(8 * 480, 116), eot(16 * 480)]

    # 轨 1：主旋律（含黑键 A#4、超音域 C6）
    melody = [
        (72, 0), (71, 480), (72, 960), (70, 1440),          # C5 B4 C5 A#4
        (69, 1920), (67, 2400), (69, 2880), (84, 3360),     # A4 G4 A4 C6(超音域)
        (72, 4320), (76, 4800), (74, 5280), (72, 5760),     # C5 E5 D5 C5
        (69, 6240), (70, 6720), (69, 7200), (67, 7680),     # A4 A#4(黑键) A4 G4
        (65, 8640), (67, 9120), (69, 9600), (72, 10080),    # F4 G4 A4 C5
        (74, 11040), (72, 11520), (69, 12000), (65, 12480), # D5 C5 A4 F4
        (67, 13440), (60, 13920), (64, 14400), (67, 14880), # G4 C4 E4 G4
    ]
    trk1 = [eot(16 * 480)]
    for pitch, tick in melody:
        trk1 += note(tick, 420, 0, pitch)

    # 轨 2：低音和弦（C3–G3，含 F#2 超低音）
    bass = [
        [(48, 0), (52, 0), (55, 0)],      # C3 E3 G3
        [(41, 1920), (45, 1920)],         # F2(超音域) A2(超音域)
        [(43, 3840), (47, 3840)],         # G2(超) B2(超)
        [(48, 5760), (52, 5760), (55, 5760)],
        [(41, 7680), (45, 7680)],
        [(43, 9600), (47, 9600)],
        [(48, 11520), (52, 11520), (55, 11520)],
        [(43, 13440), (47, 13440)],
    ]
    trk2 = [eot(16 * 480)]
    for chord in bass:
        for pitch, tick in chord:
            trk2 += note(tick, 460, 1, pitch)

    # 轨 3：打击乐（channel 9，默认忽略）
    trk3 = [eot(16 * 480)]
    for i in range(16):
        trk3.append(note_on(i * 480, 9, 36))
        trk3.append(note_off(i * 480 + 120, 9, 36))

    data = build_midi([trk0, trk1, trk2, trk3])
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "demo.mid")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    print(f"已生成 {out}（{len(data)} 字节）")


if __name__ == "__main__":
    main()
