"""综合界面自检：浅色/深色/两排键位/脚本导入 四种状态截图到 build/。

开头清除 QSettings，保证从已知状态（浅色、默认窗口尺寸）开始。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from genshin_lyre import exporter
from genshin_lyre.mapper import MapParams, map_song
from genshin_lyre.main_window import MainWindow
from genshin_lyre.midi_parser import parse_midi_file
from genshin_lyre.theme import apply_theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    QSettings("XinChengP/TestShot", "MidiGenshin").clear()
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(settings_org="XinChengP/TestShot")
    win.show()

    demo = os.path.join(ROOT, "examples", "demo.mid")
    out_dir = os.path.join(ROOT, "build")
    os.makedirs(out_dir, exist_ok=True)
    log: list[str] = []
    steps: list = []

    def shoot(name):
        path = os.path.join(out_dir, name)
        log.append(("OK  " if win.grab().save(path) else "FAIL") + " " + name)
        steps.pop(0)()

    def later(ms, fn):
        QTimer.singleShot(ms, fn)

    # 1) 浅色加载态
    def s1():
        win.load_file(demo)
        later(400, lambda: shoot("shot_loaded.png"))

    # 2) 深色
    def s2():
        assert win._dark is False, f"应为浅色起步，实际 {win._dark}"
        win._toggle_dark()
        later(400, lambda: (assert_dark(), shoot("shot_dark.png")))

    def assert_dark():
        assert win._dark is True, "深色切换未生效"

    # 3) 两排键位（深色下）
    def s3():
        win.cmb_instrument.setCurrentIndex(1)
        later(500, check_horn)

    def check_horn():
        ref = win._lbl_key_ref.text()
        assert "低音" not in ref and "中音" in ref and "高音" in ref, ref
        assert win.result.stats.dropped_range > 0, "两排应丢弃低音区音符"
        combos = [e.combo for e in win.result.events]
        assert not any(k in combos for k in ("Z", "X", "V", "B", "N", "M")), \
            "两排不应出现低音行按键"
        shoot("shot_dark_horn.png")

    # 4) 回浅色 + 脚本导入
    def s4():
        win._toggle_dark()
        later(400, s4_load)

    def s4_load():
        assert win._dark is False
        song = parse_midi_file(demo)
        result = map_song(song, MapParams())
        script_path = os.path.join(out_dir, "selfcheck_原琴.txt")
        exporter.export_script(result, MapParams(), script_path, source_name="demo.mid")
        win._load_script(script_path)
        later(400, check_script)

    def check_script():
        assert win.script_mode is True
        assert len(win.result.events) > 0
        path = os.path.join(out_dir, "shot_script.png")
        log.append(("OK  " if win.grab().save(path) else "FAIL") + " shot_script.png")
        QSettings("XinChengP/TestShot", "MidiGenshin").clear()
        app.quit()

    steps.extend([s1, s2, s3, s4])
    steps.pop(0)()
    app.exec()
    print("\n".join(log))


if __name__ == "__main__":
    main()
