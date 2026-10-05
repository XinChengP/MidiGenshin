"""可复用 UI 组件：表格模型 / 预览表格 / 分布图 / 倒计时浮窗 / Toast / 导出对话框。"""

from __future__ import annotations

import bisect
import math
import os
import time as _time

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRectF, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup,
                               QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QTableView, QVBoxLayout, QWidget)

from . import theme
from .player import STOP_KEY_VKS, is_stop_key_pressed
from .keys import pitch_name

def fmt_clock(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    return f"{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


def parse_time_text(text: str) -> float | None:
    """'83' 或 '1:23' 或 '1:23.5' -> 秒。"""
    text = text.strip()
    try:
        if ":" in text:
            parts = text.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except (ValueError, IndexError):
        return None


# ---------------- 预览列表模型 ----------------

class EventTableModel(QAbstractTableModel):
    HEADERS = ("序号", "时间", "按键组合", "保持", "说明")

    def __init__(self):
        super().__init__()
        self._rows: list[tuple] = []
        self._times: list[float] = []
        self._cursor = -1  # 播放中的当前行
        self._start_row = -1  # 用户设定的起始事件行
        self._colors = theme.get_model_colors(False)

    def set_palette(self, colors: dict[str, QColor]):
        self._colors = colors
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, len(self.HEADERS) - 1))

    def set_result(self, result: MapResult | None):
        self.beginResetModel()
        self._cursor = -1
        self._start_row = -1
        self._rows = []
        self._times = []
        if result:
            for i, e in enumerate(result.events):
                notes = []
                snapped = [pitch_name(k.pitch) for k in e.keys if k.snapped]
                if e.is_chord:
                    notes.append("和弦")
                for p in snapped:
                    notes.append(f"吸附自 {p}")
                if e.dropped_collision:
                    notes.append(f"重键丢弃 {e.dropped_collision}")
                hold = e.hold
                self._rows.append((
                    i + 1,
                    fmt_clock(e.time),
                    e.combo,
                    f"{int(round(hold * 1000))}ms",
                    " · ".join(notes),
                    e.is_chord,
                    bool(snapped),
                ))
                self._times.append(e.time)
        self.endResetModel()

    def set_start_row(self, row: int):
        old, self._start_row = self._start_row, row
        for r in {old, row}:
            if 0 <= r < len(self._rows):
                self.dataChanged.emit(self.index(r, 0),
                                      self.index(r, len(self.HEADERS) - 1))

    def set_cursor(self, idx: int):
        old, self._cursor = self._cursor, idx
        for r in (old, idx):
            if 0 <= r < len(self._rows):
                self.dataChanged.emit(self.index(r, 0), self.index(r, len(self.HEADERS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row[col]
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (0, 3):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self._cursor:
                return self._colors["cursor_bg"]
            if index.row() == self._start_row:
                return self._colors["start_bg"]
            if row[5]:
                return self._colors["chord_bg"]
        if role == Qt.ItemDataRole.ForegroundRole and col == 4 and row[6]:
            return self._colors["snap_fg"]
        if role == Qt.ItemDataRole.FontRole and col == 2:
            f = QFont("Consolas")
            f.setBold(row[5])
            return f
        return None

    def find_row_by_time(self, t: float) -> int:
        return max(0, bisect.bisect_right(self._times, t) - 1)


class PreviewTable(QTableView):
    """预览表格：Ctrl+C 复制选中行（时间<TAB>键1+键2）。"""

    def keyPressEvent(self, event):
        if (event.matches(event.StandardKey.Copy)
                and self.selectionModel() and self.selectionModel().hasSelection()):
            model = self.model()
            rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
            lines = ["\t".join(str(model.index(r, c).data())
                               for c in (1, 2)) for r in rows]
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText("\r\n".join(lines))
            event.accept()
            return
        super().keyPressEvent(event)


# ---------------- 键位分布条形图 ----------------

class KeyDistributionWidget(QWidget):
    ROW_H = 20

    def __init__(self):
        super().__init__()
        self._data: list[tuple[str, int]] = []
        self._max = 1
        self._colors = theme.get_model_colors(False)
        self._pal = theme.get_palette(False)
        self.setMinimumHeight(24)

    def set_palette(self, pal: dict, colors: dict):
        self._pal = pal
        self._colors = colors
        self.update()

    def set_data(self, usage: dict[str, int]):
        self._data = sorted(usage.items(), key=lambda x: -x[1])
        self._max = max(self._data[0][1], 1) if self._data else 1
        self.setMinimumHeight(self.ROW_H * len(self._data) + 8)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setFont(QFont("Consolas", 9))
        y = 2
        for key, count in self._data:
            p.setPen(QColor(self._pal["text"]))
            p.drawText(QRectF(0, y, 24, self.ROW_H - 2), Qt.AlignmentFlag.AlignVCenter, key)
            bar_w = max(2, (w - 100) * count / self._max)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._pal["accent"]))
            p.drawRoundedRect(QRectF(28, y + 3, bar_w, self.ROW_H - 8), 2, 2)
            p.setPen(QColor(self._pal["text2"]))
            p.drawText(QRectF(w - 66, y, 66, self.ROW_H - 2),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(count))
            y += self.ROW_H
        if not self._data:
            p.setPen(QColor(self._pal["text3"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "—")


# ---------------- 倒计时浮窗 ----------------

class CountdownOverlay(QWidget):
    finished = Signal()
    cancelled = Signal()

    def __init__(self, seconds: float, stop_key: str = "F8"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._stop_key = stop_key
        self._deadline = _time.monotonic() + seconds
        self._last_shown = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 20)
        card = QFrame()
        card.setObjectName("cdCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 16, 16, 12)
        self._num = QLabel("5")
        self._num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num.setStyleSheet("color: white; font-size: 88px; font-weight: 700;")
        tip = QLabel("即将开始演奏 · 切换到游戏窗口")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet("color: rgba(255,255,255,190); font-size: 13px;")
        esc = QLabel(f"{stop_key} / Esc 取消")
        esc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        esc.setStyleSheet("color: rgba(255,255,255,130); font-size: 12px;")
        card_lay.addWidget(self._num)
        card_lay.addWidget(tip)
        card_lay.addWidget(esc)
        lay.addWidget(card)

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def start(self):
        geo = self.screen().availableGeometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() - 60)
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()
        self._tick()

    def _tick(self):
        if is_stop_key_pressed(STOP_KEY_VKS[self._stop_key]):
            self._done(False)
            return
        remain = self._deadline - _time.monotonic()
        shown = max(0, math.ceil(remain))
        if shown != self._last_shown:
            self._last_shown = shown
            self._num.setText(str(shown))
        if remain <= 0:
            self._done(True)

    def _done(self, ok: bool):
        self._timer.stop()
        self.hide()
        (self.finished if ok else self.cancelled).emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._done(False)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#2AA68F"), 1))
        p.setBrush(QColor(24, 32, 36, 235))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)


class ToastOverlay(QWidget):
    """置顶小提示（如"演奏结束"），数秒后自动消失。"""

    def __init__(self, text: str, seconds: float = 2.0):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "background: rgba(24,32,36,235); color: white; font-size: 16px; "
            "font-weight: 600; padding: 18px 34px; border-radius: 12px; "
            "border: 1px solid #2AA68F;")
        lay.addWidget(lbl)
        self._seconds = seconds

    def show_toast(self):
        geo = self.screen().availableGeometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() - 60)
        self.show()
        self.raise_()
        QTimer.singleShot(int(self._seconds * 1000), self.close)


# ---------------- 导出对话框 ----------------

class ExportDialog(QDialog):
    def __init__(self, parent, default_path: str):
        super().__init__(parent)
        self.setWindowTitle("导出时序脚本")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(12)

        row = QHBoxLayout()
        row.addWidget(QLabel("保存位置"))
        self.path_edit = QLineEdit(default_path)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        self.header_chk = QCheckBox("包含注释头（来源与生成参数）")
        self.header_chk.setChecked(True)
        lay.addWidget(self.header_chk)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("时间格式"))
        self.rb_sec = QRadioButton("秒 (0.500)")
        self.rb_clock = QRadioButton("分:秒.毫秒 (00:00.500)")
        self.rb_sec.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_sec)
        grp.addButton(self.rb_clock)
        fmt_row.addWidget(self.rb_sec)
        fmt_row.addWidget(self.rb_clock)
        fmt_row.addStretch(1)
        lay.addLayout(fmt_row)

        self.speed_chk = QCheckBox("按当前演奏速度缩放时间")
        lay.addWidget(self.speed_chk)

        self.dur_chk = QCheckBox("包含音符时长（v2 格式，回读时可配合「跟随音符」演奏）")
        lay.addWidget(self.dur_chk)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("导出")
        ok.setObjectName("accentBtn")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出时序脚本", self.path_edit.text(),
                                              "文本文件 (*.txt)")
        if path:
            self.path_edit.setText(path)

    @property
    def path(self) -> str:
        return self.path_edit.text().strip()

    @property
    def include_header(self) -> bool:
        return self.header_chk.isChecked()

    @property
    def clock_format(self) -> bool:
        return self.rb_clock.isChecked()

    @property
    def scale_by_speed(self) -> bool:
        return self.speed_chk.isChecked()

    @property
    def include_durations(self) -> bool:
        return self.dur_chk.isChecked()
