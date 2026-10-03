"""原神原琴 MIDI 按键生成器 — 主窗口。"""

from __future__ import annotations

import bisect
import math
import os
import threading
import time as _time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, QTimer, Signal, QSettings
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen, QIcon
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QToolButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import exporter, theme
from .keys import INSTRUMENTS, WIND_HORN, WIND_LYRE, pitch_name
from .mapper import (
    HOLD_FOLLOW,
    HOLD_TAP,
    SNAP_DROP,
    SNAP_DOWN,
    SNAP_UP,
    MapParams,
    MapResult,
    dropped_summary,
    map_song,
    suggest_transpose,
)
from .midi_parser import MidiError, MidiSong, parse_midi
from .player import STOP_KEY_VKS, KeySender, Player, build_actions, is_stop_key_pressed

VERSION = "v1.1"
REPO_URL = "https://github.com/XinChengP/MidiGenshin"
ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "lyre.ico")


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
        self._colors = theme.get_model_colors(False)

    def set_palette(self, colors: dict[str, QColor]):
        self._colors = colors
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, len(self.HEADERS) - 1))

    def set_result(self, result: MapResult | None):
        self.beginResetModel()
        self._cursor = -1
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


# ---------------- 主窗口 ----------------

class MainWindow(QWidget):
    sig_progress = Signal(int)
    sig_state = Signal(str, str)
    sig_suggest_done = Signal(int)

    # ---- 主题 ----
    def _apply_dark(self, dark: bool):
        self._dark = dark
        self._pal = theme.apply_theme(QApplication.instance(), dark)
        self.model.set_palette(theme.get_model_colors(dark))
        if hasattr(self, "_key_dist"):
            self._key_dist.set_palette(self._pal, theme.get_model_colors(dark))
        if hasattr(self, "_btn_dark"):
            self._btn_dark.setText("☀" if dark else "🌙")
            self._btn_dark.setToolTip("切换深色/浅色主题")

    def _toggle_dark(self):
        self._apply_dark(not self._dark)
        self._settings.setValue("ui/dark", self._dark)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"原神原琴 MIDI 按键生成器  {VERSION}")
        self.setMinimumSize(960, 640)
        self.setAcceptDrops(True)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        self._settings = QSettings("XinChengP", "MidiGenshin")
        self._dark = self._settings.value("ui/dark", False, type=bool)
        geo = self._settings.value("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1080, 720)

        self.song: MidiSong | None = None
        self.result: MapResult | None = None
        self.player: Player | None = None
        self._overlay = None   # 持有倒计时浮窗引用，防止被 Python 回收
        self._playing = False
        self._paused = False
        self._path = ""
        self.script_mode = False          # 回读 txt 脚本模式
        self._excluded_tracks: set[int] = set()
        self._last_scroll = 0.0           # 播放跟随滚动节流
        self._rebuilding_tracks = False
        self._suggest_thread = None
        self._toast = None
        self._library: list[dict] = []   # {"path","raw","name","song","parsed_drums"}
        self._current_idx = -1
        self._rebuilding_library = False

        self.model = EventTableModel()
        self._apply_dark(self._dark)
        self._build_ui()

        self._remap_timer = QTimer(self)
        self._remap_timer.setSingleShot(True)
        self._remap_timer.setInterval(150)
        self._remap_timer.timeout.connect(self._remap)

        self.sig_progress.connect(self._on_progress)
        self.sig_state.connect(self._on_player_state)
        self.sig_suggest_done.connect(self._on_suggest_done)
        self._show_page(0)

    # ---------- UI 构建 ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_drop_page())
        self.stack.addWidget(self._build_main_page())

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self._status_label = QLabel("就绪 · 将 .mid 文件拖入窗口开始")
        status.addWidget(self._status_label)
        self._btn_dark = QToolButton()
        self._btn_dark.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._btn_dark.setAutoRaise(True)
        self._btn_dark.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dark.clicked.connect(self._toggle_dark)
        self._btn_dark.setText("☀" if self._dark else "🌙")
        self._btn_dark.setToolTip("切换深色/浅色主题")
        btn_about = QToolButton()
        btn_about.setText("关于")
        btn_about.setAutoRaise(True)
        btn_about.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_about.clicked.connect(self._show_about)
        status.addPermanentWidget(self._btn_dark)
        status.addPermanentWidget(btn_about)
        self._status_right = QLabel(f"{VERSION} · 仅前台按键模拟 · 请勿用于违规用途")
        status.addPermanentWidget(self._status_right)
        # 嵌入到底部布局
        outer.addWidget(status)

    def _build_drop_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedSize(560, 300)
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        dz = QVBoxLayout(self.drop_zone)
        dz.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("♪")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 52px; color: #34B49F;")
        t1 = QLabel("将 .mid / .midi 拖到此处（支持多选与整个文件夹）")
        t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t1.setStyleSheet("font-size: 18px; font-weight: 600; color: #1F2329;")
        t2 = QLabel("或 点击选择文件")
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2.setStyleSheet("font-size: 13px; color: #6B7280;")
        dz.addWidget(icon)
        dz.addWidget(t1)
        dz.addWidget(t2)
        self.drop_zone.mousePressEvent = lambda e: self._open_file_dialog()
        hint = QLabel("多轨合并 · 自动变速识别 · 原琴键位映射")
        hint.setStyleSheet("color: #9AA2AE; font-size: 12px;")
        lay.addWidget(self.drop_zone)
        lay.addSpacing(18)
        lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)
        return page

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(8)
        lay.addWidget(self._build_info_bar())
        lay.addWidget(self._build_params())
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_preview())
        split.addWidget(self._build_stats())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        lay.addWidget(split, 1)
        lay.addWidget(self._build_playback_bar())
        return page

    def _build_info_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("card")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        self._info_icon = QLabel("♪")
        self._info_icon.setStyleSheet("color: palette(highlight); font-size: 18px;")

        self.cmb_library = QComboBox()
        self.cmb_library.setMinimumWidth(200)
        self.cmb_library.setMaxVisibleItems(24)
        self.cmb_library.setToolTip("曲库：选择要处理的 MIDI（切换即重算）")
        self.cmb_library.currentIndexChanged.connect(self._on_library_changed)
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(32)
        self.btn_prev.setToolTip("上一曲（Ctrl+←）")
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(32)
        self.btn_next.setToolTip("下一曲（Ctrl+→）")
        self.btn_prev.clicked.connect(lambda: self._step_library(-1))
        self.btn_next.clicked.connect(lambda: self._step_library(1))
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(32)
        self.btn_remove.setToolTip("从曲库移除当前曲目")
        self.btn_remove.clicked.connect(self._remove_current)

        self._info_detail = QLabel("")
        self._info_detail.setStyleSheet("color: #6B7280;")

        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_files.clicked.connect(self._add_files_dialog)
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_add_dir.clicked.connect(self._add_dir_dialog)

        lay.addWidget(self._info_icon)
        lay.addWidget(self.cmb_library, 1)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_next)
        lay.addWidget(self.btn_remove)
        lay.addSpacing(8)
        lay.addWidget(self._info_detail, 2)
        lay.addWidget(self.btn_add_files)
        lay.addWidget(self.btn_add_dir)
        return bar

    def _build_params(self) -> QFrame:
        self._params_frame = QFrame()
        self._params_frame.setObjectName("card")
        outer = QVBoxLayout(self._params_frame)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        head = QHBoxLayout()
        self._params_toggle = QPushButton("参数 ▾")
        self._params_toggle.setFlat(True)
        self._params_toggle.setStyleSheet("color: #6B7280; border: none;")
        self._params_toggle.clicked.connect(self._toggle_params)
        self._params_summary = QLabel("")
        self._params_summary.setStyleSheet("color: #9AA2AE;")
        head.addWidget(self._params_toggle)
        head.addSpacing(8)
        head.addWidget(self._params_summary, 1)
        outer.addLayout(head)

        self._params_body = QWidget()
        grid = QGridLayout(self._params_body)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        # 第一行：乐器 / 移调 / 建议 / 黑键
        grid.addWidget(QLabel("乐器"), 0, 0)
        self.cmb_instrument = QComboBox()
        for inst in (WIND_LYRE, WIND_HORN):
            self.cmb_instrument.addItem(inst.name, inst)
        self.cmb_instrument.currentIndexChanged.connect(self._schedule_remap)
        grid.addWidget(self.cmb_instrument, 0, 1)

        grid.addWidget(QLabel("整体移调"), 0, 2)
        self.spin_transpose = QSpinBox()
        self.spin_transpose.setRange(-12, 12)
        self.spin_transpose.setSuffix(" 半音")
        self.spin_transpose.valueChanged.connect(self._schedule_remap)
        grid.addWidget(self.spin_transpose, 0, 3)
        self.btn_suggest = QPushButton("智能移调建议")
        self.btn_suggest.clicked.connect(self._suggest_transpose)
        grid.addWidget(self.btn_suggest, 0, 4)
        grid.addWidget(QLabel("黑键处理"), 0, 5)
        self.cmb_snap = QComboBox()
        self.cmb_snap.addItem("吸附 ↓ 低半音", SNAP_DOWN)
        self.cmb_snap.addItem("吸附 ↑ 高半音", SNAP_UP)
        self.cmb_snap.addItem("直接丢弃", SNAP_DROP)
        self.cmb_snap.currentIndexChanged.connect(self._schedule_remap)
        grid.addWidget(self.cmb_snap, 0, 6)
        grid.setColumnStretch(7, 1)

        # 第二行：容差 / 按键模式 / 速度 / 打击乐
        grid.addWidget(QLabel("和弦容差"), 1, 0)
        tol_box = QHBoxLayout()
        self.sld_tol = QSlider(Qt.Orientation.Horizontal)
        self.sld_tol.setRange(0, 50)
        self.sld_tol.setValue(20)
        self.sld_tol.setMaximumWidth(140)
        self.sld_tol.valueChanged.connect(self._schedule_remap)
        self.lbl_tol = QLabel("20ms")
        self.lbl_tol.setStyleSheet("color: #6B7280;")
        tol_box.addWidget(self.sld_tol)
        tol_box.addWidget(self.lbl_tol)
        grid.addLayout(tol_box, 1, 1)

        grid.addWidget(QLabel("按键模式"), 1, 2)
        self.cmb_hold = QComboBox()
        self.cmb_hold.addItem("短按（60ms）", HOLD_TAP)
        self.cmb_hold.addItem("跟随音符时长", HOLD_FOLLOW)
        self.cmb_hold.currentIndexChanged.connect(self._schedule_remap)
        grid.addWidget(self.cmb_hold, 1, 3)

        speed_box = QHBoxLayout()
        speed_box.addWidget(QLabel("演奏速度"))
        self.sld_speed = QSlider(Qt.Orientation.Horizontal)
        self.sld_speed.setRange(50, 200)
        self.sld_speed.setValue(100)
        self.sld_speed.setMaximumWidth(140)
        self.sld_speed.valueChanged.connect(self._on_speed_changed)
        self.lbl_speed = QLabel("100%")
        self.lbl_speed.setStyleSheet("color: #6B7280;")
        speed_box.addWidget(self.sld_speed)
        speed_box.addWidget(self.lbl_speed)
        speed_box.addStretch(1)
        grid.addLayout(speed_box, 1, 4)

        self.chk_drums = QCheckBox("包含打击乐通道")
        self.chk_drums.toggled.connect(self._on_drums_toggled)
        grid.addWidget(self.chk_drums, 1, 5, 1, 2)

        outer.addWidget(self._params_body)
        return self._params_frame

    def _build_preview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("跳转"))
        self.edit_jump = QLineEdit()
        self.edit_jump.setPlaceholderText("1:23 或 83.5 后回车")
        self.edit_jump.setFixedWidth(150)
        self.edit_jump.returnPressed.connect(self._jump_to_time)
        self.chk_follow = QCheckBox("播放跟随滚动")
        self.chk_follow.setChecked(True)
        tools.addWidget(self.edit_jump)
        tools.addSpacing(12)
        tools.addWidget(self.chk_follow)
        tools.addStretch(1)
        lay.addLayout(tools)

        self.table = PreviewTable()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh.setStretchLastSection(True)
        for col, width in enumerate((56, 96, 220, 70, 190)):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        lay.addWidget(self.table, 1)
        return w

    def _build_stats(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(8)

        def card(title: str) -> tuple[QFrame, QVBoxLayout]:
            f = QFrame()
            f.setObjectName("card")
            v = QVBoxLayout(f)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(4)
            t = QLabel(title)
            t.setStyleSheet("color: #6B7280; font-size: 12px; font-weight: 600;")
            v.addWidget(t)
            lay.addWidget(f)
            return f, v

        _, ov = card("概览")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._stat_labels: dict[str, QLabel] = {}
        for i, name in enumerate(("事件", "和弦组", "直击", "吸附", "丢弃", "音符")):
            v = QLabel("0")
            v.setStyleSheet("font-size: 18px; font-weight: 600;")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            k = QLabel(name)
            k.setStyleSheet("color: #9AA2AE; font-size: 11px;")
            k.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(v, 0, i)
            grid.addWidget(k, 1, i)
            self._stat_labels[name] = v
        ov.addLayout(grid)
        self._lbl_drop_detail = QLabel("")
        self._lbl_drop_detail.setWordWrap(True)
        self._lbl_drop_detail.setStyleSheet("color: #6B7280; font-size: 12px;")
        ov.addWidget(self._lbl_drop_detail)

        _, trk = card("音轨筛选")
        self._tracks_box = QVBoxLayout()
        self._tracks_box.setSpacing(2)
        trk.addLayout(self._tracks_box)
        self._lbl_tracks_hint = QLabel("")
        self._lbl_tracks_hint.setStyleSheet("color: #9AA2AE; font-size: 11px;")
        self._lbl_tracks_hint.setWordWrap(True)
        trk.addWidget(self._lbl_tracks_hint)

        _, kd = card("键位分布")
        self._key_dist = KeyDistributionWidget()
        kd.addWidget(self._key_dist)

        _, bp = card("BPM 变化")
        self._bpm_table = QTableWidget(0, 2)
        self._bpm_table.setHorizontalHeaderLabels(("时间", "BPM"))
        self._bpm_table.verticalHeader().setVisible(False)
        self._bpm_table.horizontalHeader().setStretchLastSection(True)
        self._bpm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._bpm_table.setMinimumHeight(80)
        self._bpm_table.setMaximumHeight(140)
        self._bpm_table.setStyleSheet("font-size: 12px;")
        bp.addWidget(self._bpm_table)

        _, ref = card("键位速查")
        self._lbl_key_ref = QLabel("")
        self._lbl_key_ref.setStyleSheet("font-family: Consolas; font-size: 12px; color: #374151;")
        ref.addWidget(self._lbl_key_ref)
        lay.addStretch(1)
        scroll.setWidget(body)
        return scroll

    def _build_playback_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("card")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setObjectName("playBtn")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self._on_play)
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_stop)

        lay.addWidget(QLabel("倒计时"))
        self.cmb_countdown = QComboBox()
        for s in ("0 秒", "3 秒", "5 秒", "10 秒"):
            self.cmb_countdown.addItem(s)
        self.cmb_countdown.setCurrentIndex(2)
        lay.addWidget(self.cmb_countdown)

        lay.addWidget(QLabel("急停键"))
        self.cmb_stopkey = QComboBox()
        for name in STOP_KEY_VKS:
            self.cmb_stopkey.addItem(name, STOP_KEY_VKS[name])
        self.cmb_stopkey.setCurrentIndex(0)
        self.cmb_stopkey.currentIndexChanged.connect(self._on_stopkey_changed)
        lay.addWidget(self.cmb_stopkey)

        self.sld_progress = QSlider(Qt.Orientation.Horizontal)
        self.sld_progress.setRange(0, 0)
        self.sld_progress.setEnabled(False)
        self.sld_progress.setTracking(False)  # 拖动中不触发，松手才跳播
        self.sld_progress.sliderReleased.connect(self._on_seek_released)
        lay.addWidget(self.sld_progress, 1)
        self.lbl_progress = QLabel("0/0")
        self.lbl_progress.setStyleSheet("color: #6B7280;")
        lay.addWidget(self.lbl_progress)

        self.lbl_stopkey = QLabel("F8 急停")
        self.lbl_stopkey.setStyleSheet("color: #D64545; font-weight: 600;")
        lay.addWidget(self.lbl_stopkey)

        self.btn_export = QPushButton("导出 txt")
        self.btn_export.setObjectName("accentBtn")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export)
        lay.addWidget(self.btn_export)
        return bar

    # ---------- 拖放与文件 ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                lp = url.toLocalFile()
                if lp.lower().endswith((".mid", ".midi", ".txt")) or os.path.isdir(lp):
                    event.acceptProposedAction()
                    self._set_drag_over(True)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_over(False)

    def dropEvent(self, event):
        self._set_drag_over(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        txts = [p for p in paths if p.lower().endswith(".txt")]
        if txts:
            self._load_script(txts[0])
            return
        if self.player:
            self._on_stop()
        added, errors = self._add_paths(paths)
        self._import_finish(added, errors, prefer=paths[0] if len(paths) == 1 else None)

    def _set_drag_over(self, on: bool):
        self.drop_zone.setProperty("dragOver", "true" if on else "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def _open_file_dialog(self):
        self._add_files_dialog()

    def _add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加 MIDI 文件", "",
                                                "MIDI 文件 (*.mid *.midi)")
        if not paths:
            return
        if self.player:
            self._on_stop()
        added, errors = self._add_paths(paths)
        self._import_finish(added, errors)

    def _add_dir_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "添加文件夹（递归扫描其中的 MIDI）")
        if not d:
            return
        if self.player:
            self._on_stop()
        added, errors = self._add_paths([d])
        self._import_finish(added, errors)

    def load_file(self, path: str):
        """加载并切换到指定 MIDI；已在曲库中则直接切换。"""
        if path.lower().endswith(".txt"):
            self._load_script(path)
            return
        if self.player:
            self._on_stop()
        apath = os.path.abspath(path)
        for i, e in enumerate(self._library):
            if os.path.abspath(e["path"]) == apath:
                self._switch_current(i)
                return
        added, errors = self._add_paths([path])
        if errors:
            self._show_load_error(errors[0])
            return
        if added:
            self._switch_current(added[0])

    # ---- 曲库管理 ----
    def _iter_midi_files(self, paths):
        """展开目录（递归）并过滤出 MIDI 文件。"""
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, names in os.walk(p):
                    for n in sorted(names):
                        if n.lower().endswith((".mid", ".midi")):
                            files.append(os.path.join(root, n))
            elif p.lower().endswith((".mid", ".midi")):
                files.append(p)
        return files

    def _add_paths(self, paths):
        """批量解析并加入曲库。返回 (新增条目索引列表, 错误列表)。"""
        files = self._iter_midi_files(paths)
        errors = []
        added = []
        if not files:
            return added, (["未找到 .mid / .midi 文件"] if paths else [])
        existing = {os.path.abspath(e["path"]) for e in self._library}
        names = {e["name"] for e in self._library}
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for fp in files:
                ap = os.path.abspath(fp)
                if ap in existing:
                    continue
                try:
                    with open(fp, "rb") as f:
                        raw = f.read()
                    song = parse_midi(raw, filepath=fp,
                                      include_drums=self.chk_drums.isChecked())
                except (MidiError, OSError) as e:
                    errors.append(f"{os.path.basename(fp)}：{e}")
                    continue
                name = os.path.basename(fp)
                if name in names:  # 重名曲目标注所在文件夹
                    stem = os.path.splitext(name)[0]
                    folder = os.path.basename(os.path.dirname(fp))
                    name = f"{stem} · {folder}" if folder else name
                names.add(name)
                self._library.append({"path": fp, "raw": raw, "name": name,
                                      "song": song,
                                      "parsed_drums": self.chk_drums.isChecked()})
                existing.add(ap)
                added.append(len(self._library) - 1)
        finally:
            QApplication.restoreOverrideCursor()
        if added:
            self.script_mode = False
            self._excluded_tracks = set()
            self._show_page(1)
            self._set_script_ui(False)
            self._update_library_combo()
        return added, errors

    def _import_finish(self, added, errors, prefer=None):
        """批量导入后的收尾：选择目标曲目并汇报结果。"""
        if prefer:
            ap = os.path.abspath(prefer)
            for i, e in enumerate(self._library):
                if os.path.abspath(e["path"]) == ap:
                    added = [i] + [x for x in added if x != i]
                    break
        if added:
            self._switch_current(added[0])
        msg = f"已添加 {len(added)} 首 · 曲库共 {len(self._library)} 首"
        if errors:
            msg += f" · 失败 {len(errors)}：{errors[0]}"
            if len(errors) > 1:
                msg += " 等"
        self._set_status(msg)

    def _entry_song(self, entry):
        """取条目曲目（含打击乐开关的解析缓存）。"""
        drums = self.chk_drums.isChecked()
        if entry["song"] is None or entry["parsed_drums"] != drums:
            entry["song"] = parse_midi(entry["raw"], filepath=entry["path"],
                                       include_drums=drums)
            entry["parsed_drums"] = drums
        return entry["song"]

    def _switch_current(self, idx):
        if not (0 <= idx < len(self._library)):
            return
        self._current_idx = idx
        entry = self._library[idx]
        self.song = self._entry_song(entry)
        self._path = entry["path"]
        self.script_mode = False
        self._excluded_tracks = set()
        self._show_page(1)
        self._set_script_ui(False)
        self._update_library_combo()
        self._update_info_bar()
        self._remap()
        self._set_status(f"已切换到 {entry['name']} · {len(self.song.notes)} 音符")

    def _on_library_changed(self, idx):
        if self._rebuilding_library or idx == self._current_idx or idx < 0:
            return
        if self.player:
            self._on_stop()
        self._switch_current(idx)

    def _step_library(self, step):
        if len(self._library) < 2:
            return
        self._switch_current((self._current_idx + step) % len(self._library))

    def _remove_current(self):
        if not self._library:
            return
        if self.player:
            self._on_stop()
        del self._library[self._current_idx]
        if not self._library:
            self._current_idx = -1
            self.song = None
            self.result = None
            self._update_library_combo()
            self._show_page(0)
            self._set_status("曲库已清空 · 将 .mid 文件拖入窗口开始")
            return
        self._switch_current(min(self._current_idx, len(self._library) - 1))

    def _update_library_combo(self):
        self._rebuilding_library = True
        self.cmb_library.clear()
        for i, e in enumerate(self._library):
            self.cmb_library.addItem(e["name"], i)
        if 0 <= self._current_idx < len(self._library):
            self.cmb_library.setCurrentIndex(self._current_idx)
        multi = len(self._library) > 1
        for w in (self.btn_prev, self.btn_next, self.btn_remove):
            w.setEnabled(multi)
        self._rebuilding_library = False

    def _load_script(self, path: str):
        """回读导出的 txt 时序脚本（可再预览与播放）。"""
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                _, result, meta = exporter.parse_script(path)
            finally:
                QApplication.restoreOverrideCursor()
        except (ValueError, OSError) as e:
            self._show_load_error(f"无法读取脚本：{e}")
            return
        self.song = None
        self.script_mode = True
        self._path = path
        self.result = result
        self._show_page(1)
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        self._info_detail.setText(f"时序脚本 · {len(result.events)} 事件"
                                  + (f" · 来源 {meta['source']}" if meta["source"] else ""))
        self._set_script_ui(True)
        self._apply_result()
        self._set_status(f"已导入脚本 {name} · {len(result.events)} 事件 · 可直接播放")

    def _set_script_ui(self, script: bool):
        """脚本模式下禁用与 MIDI 解析相关的参数，并隐藏曲目导航。"""
        for w in (self.cmb_library, self.btn_prev, self.btn_next, self.btn_remove):
            w.setVisible(not script)
        for w in (self.cmb_instrument, self.spin_transpose, self.btn_suggest,
                  self.cmb_snap, self.sld_tol, self.chk_drums):
            w.setEnabled(not script and not self._playing)

    def _show_load_error(self, msg: str):
        self._info_detail.setText("加载失败：" + msg)
        self._set_status("加载失败")
        QMessageBox.warning(self, "无法加载 MIDI", msg)

    def _update_info_bar(self):
        s = self.song
        if not s:
            return
        detail = (f"{fmt_clock(s.duration)} · {s.track_count} 轨 · {len(s.notes)} 音符 · "
                  f"BPM {s.bpm_display:g}"
                  + (f"（{len(s.tempo_changes)} 处变速）" if len(s.tempo_changes) > 1 else ""))
        if len(self._library) > 1:
            detail += f" · 曲库 {len(self._library)} 首"
        self._info_detail.setText(detail)

    # ---------- 映射与刷新 ----------
    def _current_params(self) -> MapParams:
        return MapParams(
            instrument=self.cmb_instrument.currentData() or WIND_LYRE,
            transpose=self.spin_transpose.value(),
            snap=self.cmb_snap.currentData(),
            chord_tol=self.sld_tol.value() / 1000.0,
            hold_mode=self.cmb_hold.currentData(),
        )

    @property
    def speed(self) -> float:
        return self.sld_speed.value() / 100.0

    def _schedule_remap(self):
        self.lbl_tol.setText(f"{self.sld_tol.value()}ms")
        self._remap_timer.start()

    def _on_speed_changed(self):
        self.lbl_speed.setText(f"{self.sld_speed.value()}%")
        self._update_params_summary()

    def _on_drums_toggled(self):
        for e in self._library:
            e["parsed_drums"] = None  # 缓存失效，切换/重算时按新开关重解析
        if self.song is not None and 0 <= self._current_idx < len(self._library):
            self.song = self._entry_song(self._library[self._current_idx])
            self._update_info_bar()
        self._schedule_remap()

    def _remap(self):
        if self.script_mode:
            return  # 脚本模式无参数可重算
        if not self.song:
            return
        self.result = map_song(self.song, self._current_params(),
                               exclude_tracks=frozenset(self._excluded_tracks))
        self._apply_result()

    def _apply_result(self):
        """把 self.result 应用到列表/统计/按钮（MIDI 与脚本模式共用）。"""
        self.model.set_result(self.result)
        self.sld_progress.setRange(0, max(0, len(self.result.events) - 1))
        self.sld_progress.setValue(0)
        self._update_stats()
        self._update_params_summary()
        has = bool(self.result.events)
        self.btn_play.setEnabled(has and not self._playing)
        self.btn_export.setEnabled(has and not self._playing)
        if not has:
            self._set_status("没有可演奏的音符：尝试调整移调、黑键策略或切换乐器")

    def _update_stats(self):
        s = self.result.stats
        vals = {"事件": len(self.result.events), "和弦组": s.chord_groups,
                "直击": s.direct, "吸附": s.snapped, "丢弃": s.dropped,
                "音符": s.total}
        for k, v in vals.items():
            lbl = self._stat_labels[k]
            lbl.setText(str(v))
            style = "font-size: 18px; font-weight: 600;"
            if k == "丢弃" and v:
                style += " color: #D64545;"
            lbl.setStyleSheet(style)
        self._lbl_drop_detail.setText(dropped_summary(self.result) if s.total else "")
        self._key_dist.set_data(self.result.key_usage)

        tc = self.song.tempo_changes if self.song else []
        self._bpm_table.setRowCount(len(tc))
        for i, t in enumerate(tc):
            self._bpm_table.setItem(i, 0, QTableWidgetItem(fmt_clock(t.time)))
            self._bpm_table.setItem(i, 1, QTableWidgetItem(f"{t.bpm:.1f}"))
        if not self.song:
            self._bpm_table.setRowCount(1)
            self._bpm_table.setItem(0, 0, QTableWidgetItem("—"))
            self._bpm_table.setItem(0, 1, QTableWidgetItem("脚本无 BPM"))

        inst = self._current_params().instrument
        ref_lines = [f"{label}  {' '.join(row)}"
                     for label, row in zip(inst.row_labels, inst.rows)]
        span = "低/中/高三组" if len(inst.rows) == 3 else "中/高两组"
        ref_lines.append(f"C 大调 {span} do–si（MIDI {inst.pitch_min}–{inst.pitch_max}）")
        self._lbl_key_ref.setText("\n".join(ref_lines))
        self._update_track_card()

    def _update_track_card(self):
        """重建音轨筛选复选框（脚本模式清空）。"""
        self._rebuilding_tracks = True
        while self._tracks_box.count():
            item = self._tracks_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self.song:
            self._lbl_tracks_hint.setText("（脚本模式无音轨）")
            self._rebuilding_tracks = False
            return
        counts: dict[int, int] = {}
        for n in self.song.notes:
            counts[n.track] = counts.get(n.track, 0) + 1
        for trk in sorted(counts):
            cb = QCheckBox(f"轨 {trk + 1} · {counts[trk]} 音符")
            cb.setChecked(trk not in self._excluded_tracks)
            cb.toggled.connect(lambda on, t=trk: self._on_track_toggled(t, on))
            self._tracks_box.addWidget(cb)
        self._lbl_tracks_hint.setText("取消勾选的音轨不参与映射" if len(counts) > 1 else "")
        self._rebuilding_tracks = False

    def _on_track_toggled(self, track: int, on: bool):
        if self._rebuilding_tracks:
            return
        if on:
            self._excluded_tracks.discard(track)
        else:
            self._excluded_tracks.add(track)
        self._schedule_remap()

    def _update_params_summary(self):
        if self.script_mode:
            self._params_summary.setText("时序脚本 · 按键模式与演奏速度可调")
            return
        p = self._current_params()
        snap_txt = self.cmb_snap.currentText().split(" ")[0]
        self._params_summary.setText(
            f"{p.instrument.name} · 移调 {p.transpose:+d} · {snap_txt} · "
            f"容差 {int(p.chord_tol * 1000)}ms · "
            f"{'短按' if p.hold_mode == HOLD_TAP else '跟随'} · {self.sld_speed.value()}%")

    def _toggle_params(self):
        show = not self._params_body.isVisible()
        self._params_body.setVisible(show)
        self._params_toggle.setText("参数 ▾" if show else "参数 ▸")

    def _suggest_transpose(self):
        if not self.song or self._suggest_thread:
            return
        song, params = self.song, self._current_params()
        self.btn_suggest.setEnabled(False)
        self.btn_suggest.setText("计算中…")
        self._set_status("正在计算移调建议…")

        def work():
            best = suggest_transpose(song, params)
            self.sig_suggest_done.emit(best)

        self._suggest_thread = threading.Thread(target=work, daemon=True)
        self._suggest_thread.start()

    def _on_suggest_done(self, best: int):
        self._suggest_thread = None
        self.btn_suggest.setEnabled(bool(self.song) and not self._playing)
        self.btn_suggest.setText("智能移调建议")
        if self.song:
            self.spin_transpose.setValue(best)
            self._set_status(f"已应用移调建议：{best:+d} 半音（丢弃数最少）")

    def _jump_to_time(self):
        t = parse_time_text(self.edit_jump.text())
        if t is None or not self.result or not self.result.events:
            return
        row = self.model.find_row_by_time(t)
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0),
                            QAbstractItemView.ScrollHint.PositionAtCenter)

    # ---------- 播放 ----------
    def _on_play(self):
        if not self.result or self._playing:
            return
        secs = (0, 3, 5, 10)[self.cmb_countdown.currentIndex()]
        self.btn_play.setEnabled(False)
        self._set_status("倒计时…" if secs else "准备开始…")
        if secs <= 0:
            self._start_playback()
        else:
            ov = CountdownOverlay(float(secs), self.cmb_stopkey.currentText())
            ov.finished.connect(self._start_playback)
            ov.cancelled.connect(self._on_countdown_cancelled)
            self._overlay = ov   # 必须持有引用，否则离开函数即被销毁
            ov.start()

    def _on_countdown_cancelled(self):
        self._overlay = None
        self._set_playing_ui(False)
        self._set_status("已取消倒计时")

    def _start_playback(self):
        self._overlay = None
        if not self.result:
            return
        actions = build_actions(self.result.events, self.speed,
                                self._current_params().hold_mode)
        sender = KeySender()
        self.player = Player(
            actions, sender,
            on_progress=lambda idx: self.sig_progress.emit(idx),
            on_state=lambda s, d: self.sig_state.emit(s, d),
            focus_guard_hwnd=int(self.winId()),
            stop_vk=self.cmb_stopkey.currentData(),
        )
        self._playing = True
        self._paused = False
        self._set_playing_ui(True)
        self.player.start()

    def _on_pause(self):
        if not self.player:
            return
        if self._paused:
            self.player.resume()
            self._paused = False
            self.btn_pause.setText("⏸ 暂停")
        else:
            self.player.pause()
            self._paused = True
            self.btn_pause.setText("▶ 继续")

    def _on_stop(self):
        if self.player:
            self.player.stop()

    def _on_progress(self, idx: int):
        self.sld_progress.setValue(idx)
        self.lbl_progress.setText(f"{idx + 1}/{len(self.result.events) if self.result else 0}")
        self.model.set_cursor(idx)
        now = _time.monotonic()
        if self.chk_follow.isChecked() and now - self._last_scroll >= 0.03:
            self._last_scroll = now
            self.table.selectRow(idx)
            self.table.scrollTo(self.model.index(idx, 0),
                                QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_player_state(self, state: str, detail: str):
        if state == "running":
            self._paused = False
            self.btn_pause.setText("⏸ 暂停")
            self.btn_pause.setStyleSheet("")
            self._set_status("演奏中 · F8 急停")
        elif state == "paused":
            self._paused = True
            self.btn_pause.setText("▶ 继续")
            # 高亮提醒：当前处于暂停态，避免误以为按钮仍是"暂停"
            self.btn_pause.setStyleSheet(
                "background: #FFF3E0; border: 1px solid #E8A33D; color: #B4761F; font-weight: 600;")
            if detail == "focus":
                self._set_status("⏸ 已自动暂停：演奏窗口切回了本工具 · 切回游戏后点「▶ 继续」")
            else:
                self._set_status("⏸ 已暂停 · 点「▶ 继续」恢复")
        elif state == "finished":
            self._finish_playback("演奏结束")
        elif state == "stopped":
            self._finish_playback("已停止")
        elif state == "aborted":
            self._finish_playback("已通过 F8 急停")
        elif state == "error":
            self._finish_playback(detail)
            QMessageBox.warning(self, "演奏中止", detail)

    def _finish_playback(self, msg: str):
        self._playing = False
        self._paused = False
        self.player = None
        self.btn_pause.setText("⏸ 暂停")
        self.btn_pause.setStyleSheet("")
        self._set_playing_ui(False)
        self.model.set_cursor(-1)
        self._set_status(msg)
        if msg == "演奏结束":
            self._toast = ToastOverlay("♪ 演奏结束")
            self._toast.show_toast()

    def _set_playing_ui(self, playing: bool):
        self.btn_play.setEnabled(not playing and bool(self.result and self.result.events))
        self.btn_pause.setEnabled(playing)
        self.btn_stop.setEnabled(playing)
        self.btn_export.setEnabled(not playing and bool(self.result and self.result.events))
        self._set_script_ui(self.script_mode)
        self.cmb_hold.setEnabled(not playing)
        self.sld_speed.setEnabled(not playing)
        self.cmb_stopkey.setEnabled(not playing)
        self.sld_progress.setEnabled(playing)

    def _on_stopkey_changed(self):
        name = self.cmb_stopkey.currentText()
        self.lbl_stopkey.setText(f"{name} 急停")

    def _on_seek_released(self):
        """进度条跳播：跳到滑块所在事件继续演奏。"""
        if not (self.player and self.result and self._playing):
            return
        idx = self.sld_progress.value()
        self.player.seek(idx)
        self.model.set_cursor(idx)
        row = self.model.index(idx, 0)
        self.table.scrollTo(row, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle("关于")
        box.setText(
            f"<b>原神原琴 MIDI 按键生成器 {VERSION}</b><br><br>"
            "读取 MIDI，转换为原琴按键时序并自动演奏。<br>"
            f"项目主页：<a href='{REPO_URL}'>{REPO_URL}</a><br><br>"
            "仅前台按键模拟，不含任何注入或反检测设计。<br>"
            "自动化输入可能违反游戏用户协议，仅供单机/离线练习，风险自负。")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.exec()

    # ---------- 导出 ----------
    def _on_export(self):
        if not self.result:
            return
        if self.song:
            stem = (self.song.filename or "output").rsplit(".", 1)[0]
        else:
            stem = (self._path.replace("\\", "/").rsplit("/", 1)[-1] or "output")
            if stem.endswith(".txt"):
                stem = stem[:-4]
        folder = os.path.dirname(self._path) if self._path else ""
        default = os.path.join(folder or ".", stem + "_原琴.txt")
        dlg = ExportDialog(self, default)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.path:
            return
        try:
            if self.song:
                source = self.song.filename
            else:
                source = self._path.replace("\\", "/").rsplit("/", 1)[-1]
            n = exporter.export_script(
                self.result, self._current_params(), dlg.path,
                source_name=source,
                include_header=dlg.include_header,
                clock_format=dlg.clock_format,
                speed=self.speed if dlg.scale_by_speed else 1.0,
            )
            self._set_status(f"导出成功：{dlg.path}（{n} 个事件）")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"写入文件失败：{e}")

    # ---------- 杂项 ----------
    def _show_page(self, idx: int):
        self.stack.setCurrentIndex(idx)

    def _set_status(self, msg: str):
        self._status_label.setText(msg)

    def keyPressEvent(self, event):
        key = event.key()
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Escape and self._playing:
            self._on_stop()
        elif ctrl and key == Qt.Key.Key_O:
            self._add_files_dialog()
        elif ctrl and key == Qt.Key.Key_Left:
            self._step_library(-1)
        elif ctrl and key == Qt.Key.Key_Right:
            self._step_library(1)
        elif ctrl and key == Qt.Key.Key_S:
            self._on_export()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._settings.setValue("ui/geometry", self.saveGeometry())
        if self.player:
            self.player.stop()
            self.player.join(timeout=1.0)  # 等线程释放按键，避免残留卡键
            self.player = None
        super().closeEvent(event)
