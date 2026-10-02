"""自检：切换晚风圆号后的界面与映射效果。输出 build/shot_horn.png"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from genshin_lyre.main_window import MainWindow
from genshin_lyre.theme import apply_theme


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()
    win.load_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "examples", "demo.mid"))

    lyre_dropped = win.result.stats.dropped_range
    win.cmb_instrument.setCurrentIndex(1)  # 晚风圆号

    def verify_and_shoot():
        inst = win._current_params().instrument
        assert inst.name == "晚风圆号", inst.name
        ref = win._lbl_key_ref.text()
        assert "低音" not in ref and "中音" in ref and "高音" in ref, ref
        horn_dropped = win.result.stats.dropped_range
        print(f"键位速查：{ref!r}")
        print(f"丢弃数：琴 {lyre_dropped} -> 圆号 {horn_dropped}（低音区被弃，应增加）")
        assert horn_dropped > lyre_dropped
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "build", "shot_horn.png")
        win.grab().save(out)
        print(f"已保存 {out}")
        app.quit()

    QTimer.singleShot(600, verify_and_shoot)
    app.exec()


if __name__ == "__main__":
    main()
