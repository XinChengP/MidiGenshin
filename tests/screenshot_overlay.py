"""自检：截取倒计时浮窗外观。运行后输出 build/shot_overlay.png"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from genshin_lyre.main_window import CountdownOverlay
from genshin_lyre.theme import apply_theme


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    overlay = CountdownOverlay(5)
    overlay.finished.connect(lambda: None)
    overlay.cancelled.connect(lambda: None)
    overlay.start()

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "build", "shot_overlay.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    def grab():
        overlay.grab().save(out)
        app.quit()

    QTimer.singleShot(700, grab)
    app.exec()
    print(f"已保存 {out}")


if __name__ == "__main__":
    main()
