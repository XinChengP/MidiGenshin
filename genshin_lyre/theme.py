"""浅色主题样式（对应界面布局描述 §8 视觉规格）。"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

ACCENT = "#34B49F"
ACCENT_DARK = "#2AA68F"

QSS = f"""
QWidget {{
    background: #F7F8FA;
    color: #1F2329;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QFrame#card {{
    background: #FFFFFF;
    border: 1px solid #E3E6EB;
    border-radius: 8px;
}}
QFrame#dropZone {{
    background: #FFFFFF;
    border: 2px dashed #B8BEC9;
    border-radius: 12px;
}}
QFrame#dropZone[dragOver="true"] {{
    background: #ECF9F6;
    border: 2px dashed {ACCENT};
}}
QFrame#cdCard {{ background: transparent; }}
QPushButton {{
    background: #FFFFFF;
    border: 1px solid #D6DAE1;
    border-radius: 6px;
    padding: 5px 14px;
}}
QPushButton:hover {{ background: #F0F2F5; }}
QPushButton:pressed {{ background: #E7EAEE; }}
QPushButton:disabled {{ color: #A8AEB8; background: #F2F3F5; }}
QPushButton#playBtn {{
    background: {ACCENT};
    color: white;
    border: none;
    padding: 6px 22px;
    font-weight: 600;
}}
QPushButton#playBtn:hover {{ background: {ACCENT_DARK}; }}
QPushButton#playBtn:disabled {{ background: #A8D8CF; color: #FFFFFF; }}
QPushButton#accentBtn {{
    background: {ACCENT};
    color: white;
    border: none;
    font-weight: 600;
}}
QPushButton#accentBtn:hover {{ background: {ACCENT_DARK}; }}
QPushButton:flat, QPushButton[flat="true"] {{ border: none; background: transparent; }}

QTableView {{
    background: #FFFFFF;
    alternate-background-color: #FAFBFC;
    border: 1px solid #E3E6EB;
    border-radius: 8px;
    selection-background-color: #D9F2ED;
    selection-color: #1F2329;
    gridline-color: transparent;
}}
QHeaderView::section {{
    background: #F1F3F6;
    border: none;
    border-bottom: 1px solid #E3E6EB;
    padding: 5px 6px;
    font-weight: 600;
    color: #374151;
}}
QTableWidget {{
    background: #FFFFFF;
    border: 1px solid #E3E6EB;
    border-radius: 6px;
}}
QLineEdit, QComboBox, QSpinBox {{
    background: #FFFFFF;
    border: 1px solid #D6DAE1;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QSlider::groove:horizontal {{
    height: 5px;
    border-radius: 2px;
    background: #E3E6EB;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #FFFFFF;
    border: 1px solid {ACCENT};
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QStatusBar {{
    background: transparent;
    border-top: 1px solid #E3E6EB;
    color: #6B7280;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #C9CFD8; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #AeB6C2; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{
    background: #2B3138; color: white; border: none; padding: 4px 8px;
}}
QMessageBox {{ background: #FFFFFF; }}
"""


def apply_theme(app: QApplication):
    app.setStyleSheet(QSS)
