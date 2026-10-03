"""曲库模式截图自检：多曲目下拉/导航按钮/信息条。输出 build/shot_library.png"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from genshin_lyre.main_window import MainWindow
from genshin_lyre.theme import apply_theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    QSettings("XinChengP", "MidiGenshin").clear()
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()

    tmp = tempfile.mkdtemp(prefix="lyre_shot_")
    demo = os.path.join(ROOT, "examples", "demo.mid")
    b = os.path.join(tmp, "另一首.mid")
    shutil.copy(demo, b)

    def step1():
        win.load_file(demo)
        added, errors = win._add_paths([b])
        assert len(added) == 1 and not errors
        win._step_library(1)  # 切到“另一首.mid”
        assert win.cmb_library.currentText() == "另一首.mid"
        assert len(win._library) == 2
        QTimer.singleShot(300, shoot)

    def shoot():
        out = os.path.join(ROOT, "build", "shot_library.png")
        ok = win.grab().save(out)
        QSettings("XinChengP", "MidiGenshin").clear()
        shutil.rmtree(tmp, ignore_errors=True)
        print(("OK  " if ok else "FAIL") + " shot_library.png")
        app.quit()

    QTimer.singleShot(100, step1)
    app.exec()


if __name__ == "__main__":
    main()
