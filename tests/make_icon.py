"""生成应用图标 assets/lyre.ico：三排琴键 + 原琴青绿点缀。

运行：python tests/make_icon.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 100.0  # 以 100 为设计基准

    # 圆角底板（深青黑）
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#18242A"))
    p.drawRoundedRect(QRectF(4 * s, 4 * s, 92 * s, 92 * s), 18 * s, 18 * s)

    # 三排琴键
    rows = [("Z X C V B N M", False), ("A S D F G H J", True), ("Q W E R T Y U", False)]
    font = QFont("Consolas")
    font.setBold(True)
    p.setFont(font)
    y0 = 14 * s
    row_h = 24 * s
    key_w = 11 * s
    gap = 1.5 * s
    for r, (_, highlight) in enumerate(rows):
        y = y0 + r * (row_h + 3 * s)
        for i in range(7):
            x = 12 * s + i * (key_w + gap)
            if highlight:
                p.setBrush(QColor("#34B49F"))
                p.setPen(Qt.PenStyle.NoPen)
            else:
                p.setBrush(QColor("#EDF1F4"))
                p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y, key_w, row_h), 3 * s, 3 * s)
    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    # ico 由多尺寸合成：QPixmap.save 直接支持 ico（取单图）
    pm = draw_pixmap(256)
    out = os.path.join(ROOT, "assets", "lyre.ico")
    ok = pm.save(out)
    pm.save(os.path.join(ROOT, "assets", "lyre@256.png"))
    print(("已生成 " if ok else "生成失败 ") + out)
    # 预览小尺寸是否清晰
    for s in (16, 32, 64):
        draw_pixmap(s).save(os.path.join(ROOT, "assets", f"preview_{s}.png"))
    app.quit()


if __name__ == "__main__":
    main()
