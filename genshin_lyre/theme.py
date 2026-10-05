"""应用主题：浅色 / 深色两套 QSS 与预览列表配色板。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F7F8FA", "card": "#FFFFFF", "border": "#E3E6EB",
        "text": "#1F2329", "text2": "#6B7280", "text3": "#9AA2AE",
        "accent": "#34B49F", "accent_dk": "#2AA68F",
        "hover": "#F0F2F5", "pressed": "#E7EAEE", "disabled_bg": "#F2F3F5",
        "input_border": "#D6DAE1", "table_alt": "#FAFBFC", "selection": "#D9F2ED",
        "header_bg": "#F1F3F6", "scroll": "#C9CFD8", "scroll_hov": "#AEB6C2",
        "groove": "#E3E6EB", "handle_bg": "#FFFFFF",
        "tooltip_bg": "#2B3138", "tooltip_fg": "#FFFFFF",
        "menu_bg": "#FFFFFF", "menu_item_sel": "#E9F7F4",
    },
    "dark": {
        "bg": "#1B1F23", "card": "#24292E", "border": "#33393F",
        "text": "#E6E8EA", "text2": "#9AA2AE", "text3": "#707A85",
        "accent": "#3DC7A0", "accent_dk": "#34B49F",
        "hover": "#2D3339", "pressed": "#333A41", "disabled_bg": "#22272C",
        "input_border": "#444C54", "table_alt": "#20262B", "selection": "#2A5F55",
        "header_bg": "#20262B", "scroll": "#3A4148", "scroll_hov": "#4A525A",
        "groove": "#3A4148", "handle_bg": "#24292E",
        "tooltip_bg": "#E6E8EA", "tooltip_fg": "#1B1F23",
        "menu_bg": "#24292E", "menu_item_sel": "#2A5F55",
    },
}

# 预览列表 / 统计等由代码绘制处使用的颜色
MODEL_COLORS: dict[str, dict[str, str]] = {
    "light": {"chord_bg": "#E9F7F4", "cursor_bg": "#FFEFC2", "start_bg": "#FFDFA6",
              "snap_fg": "#B4761F", "drop_fg": "#D64545", "drop_num_fg": "#D64545"},
    "dark": {"chord_bg": "#1F3B36", "cursor_bg": "#4A3F1E", "start_bg": "#5A451C",
             "snap_fg": "#E8A33D", "drop_fg": "#FF8A8A", "drop_num_fg": "#FF8A8A"},
}


def get_palette(dark: bool) -> dict[str, str]:
    return PALETTES["dark" if dark else "light"]


def get_model_colors(dark: bool) -> dict[str, QColor]:
    return {k: QColor(v) for k, v in MODEL_COLORS["dark" if dark else "light"].items()}


def build_qss(dark: bool) -> str:
    p = get_palette(dark)
    return f"""
QWidget {{
    background: {p['bg']};
    color: {p['text']};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QFrame#card {{
    background: {p['card']};
    border: 1px solid {p['border']};
    border-radius: 8px;
}}
QFrame#dropZone {{
    background: {p['card']};
    border: 2px dashed {p['input_border']};
    border-radius: 12px;
}}
QFrame#dropZone[dragOver="true"] {{
    background: {p['menu_item_sel']};
    border: 2px dashed {p['accent']};
}}
QFrame#cdCard {{ background: transparent; }}
QPushButton {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['input_border']};
    border-radius: 6px;
    padding: 5px 14px;
}}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ color: {p['text3']}; background: {p['disabled_bg']}; }}
QPushButton#playBtn {{
    background: {p['accent']};
    color: white;
    border: none;
    padding: 6px 22px;
    font-weight: 600;
}}
QPushButton#playBtn:hover {{ background: {p['accent_dk']}; }}
QPushButton#playBtn:disabled {{ background: {p['accent']}; color: rgba(255,255,255,160); }}
QPushButton#accentBtn {{
    background: {p['accent']};
    color: white;
    border: none;
    font-weight: 600;
}}
QPushButton#accentBtn:hover {{ background: {p['accent_dk']}; }}

QTableView {{
    background: {p['card']};
    alternate-background-color: {p['table_alt']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    selection-background-color: {p['selection']};
    selection-color: {p['text']};
    gridline-color: transparent;
}}
QHeaderView::section {{
    background: {p['header_bg']};
    border: none;
    border-bottom: 1px solid {p['border']};
    padding: 5px 6px;
    font-weight: 600;
    color: {p['text2']};
}}
QTableWidget {{
    background: {p['card']};
    alternate-background-color: {p['table_alt']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
}}
QTableWidget::item:selected {{ background: {p['selection']}; }}
QLineEdit, QComboBox, QSpinBox {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['input_border']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {p['accent']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {p['menu_bg']};
    color: {p['text']};
    selection-background-color: {p['menu_item_sel']};
    selection-color: {p['text']};
}}
QMenu {{
    background: {p['menu_bg']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}
QMenu::item:selected {{ background: {p['menu_item_sel']}; }}
QSlider::groove:horizontal {{
    height: 5px;
    border-radius: 2px;
    background: {p['groove']};
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {p['handle_bg']};
    border: 1px solid {p['accent']};
}}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
QStatusBar {{
    background: transparent;
    border-top: 1px solid {p['border']};
    color: {p['text2']};
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['scroll']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['scroll_hov']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {p['scroll']}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['scroll_hov']}; }}
QToolTip {{
    background: {p['tooltip_bg']}; color: {p['tooltip_fg']}; border: none; padding: 4px 8px;
}}
QMessageBox {{ background: {p['card']}; }}
QCheckBox, QRadioButton {{ background: transparent; }}
"""


def apply_theme(app: QApplication, dark: bool = False) -> dict[str, str]:
    """应用主题并返回配色板（供绘制处使用）。"""
    app.setStyleSheet(build_qss(dark))
    return get_palette(dark)
