"""起点功能测试：右键设起点 → 播放从该事件开始（时间轴前移、不空等）。

运行：python tests/test_start_from.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import genshin_lyre.main_window as mw
import genshin_lyre.player as player_mod
from genshin_lyre.main_window import MainWindow
from genshin_lyre.theme import apply_theme

PASS = 0


def check(name, cond, detail=""):
    global PASS
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        raise AssertionError(name)
    PASS += 1


def main():
    QSettings("XinChengP/Test", "MidiGenshin").clear()
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(settings_org="XinChengP/Test")
    win.show()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    win.load_file(os.path.join(root, "examples", "demo.mid"))

    # 0) 等待加载后的自动调整完成（会重算一次）
    entry = win._library[win._current_idx]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not entry.get("auto_done"):
        app.processEvents()
        time.sleep(0.02)
    assert entry.get("auto_done"), "自动调整未完成"

    # 1) 设置起点（事件 15，约 7.4s）
    row = 15
    win.set_start_from_row(row)
    check("起点行标记", win.model._start_row == row)
    check("起点标签可见", win.lbl_start.isVisible() and "起点" in win.lbl_start.text())
    check("进度条同步", win.sld_progress.value() == row)
    t0 = win.result.events[row].time

    # 2) dry-run 播放：首个按键应立即出现且从事件 15 开始（不等待 7.4s）
    _sent = mw.KeySender
    mw.KeySender = lambda: player_mod.KeySender(dry_run=True)
    progress = []
    win.cmb_countdown.setCurrentIndex(0)  # 无倒计时
    real_sender_holder = {}
    win._start_playback()
    # 替换 progress 回调起点验证：直接查 sender.log
    player = win.player
    assert player is not None
    player.on_progress = lambda idx: progress.append(idx)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(progress) < 3:
        app.processEvents()
        time.sleep(0.02)
    win._on_stop()
    player.join(timeout=3)
    mw.KeySender = _sent

    check("收到进度", len(progress) >= 3, str(progress[:5]))
    check("首事件即起点", progress and progress[0] == row, str(progress[:5]))
    downs = [t for t, k, key in player.sender.log if k == "down"]
    check("起点即刻发声（<0.6s，无 7.4s 空等）", downs and downs[0] < 0.6,
          f"first={downs[0]:.2f}s" if downs else "无")
    check("时间轴已前移", downs and abs(downs[0] - 0.0) < 0.5, f"{downs[0]:.3f}")

    # 3) 清除起点
    win._clear_start()
    check("清除后起点复位", win._start_event_idx == 0 and not win.lbl_start.isVisible())

    # 4) 重算（参数变化）会重置起点
    win.set_start_from_row(5)
    win.sld_tol.setValue(25)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    check("重算后起点重置", win._start_event_idx == 0 and win.model._start_row == -1)

    win.close()
    QSettings("XinChengP/Test", "MidiGenshin").clear()
    print(f"\n全部通过：{PASS} 项检查")


if __name__ == "__main__":
    main()
