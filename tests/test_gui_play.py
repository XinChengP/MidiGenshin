"""GUI 播放链路回归测试：点播放 → 倒计时浮窗存活 → 结束后进入演奏。

背景：浮窗曾是 _on_play 的局部变量，函数返回即被 Python 回收，
导致"点播放没反应"。本测试持有 MainWindow 引用走真实流程；
发送器替换为 dry-run，不会向任何窗口发送按键。

运行：python tests/test_gui_play.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
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
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()

    # 加载演示曲（同步解析+映射）
    win.load_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "examples", "demo.mid"))
    check("加载后播放按钮可用", win.btn_play.isEnabled())
    check("已生成事件序列", bool(win.result and win.result.events))

    # 替换发送器为 dry-run：真实流程但不发送任何按键
    sent = mw.KeySender
    mw.KeySender = lambda: player_mod.KeySender(dry_run=True)

    started = []
    win.cmb_countdown.setCurrentIndex(1)  # 3 秒
    real_start = win._start_playback

    def tracked_start():
        started.append(True)
        real_start()

    win._start_playback = tracked_start
    win._on_play()

    check("点击后浮窗对象存在", win._overlay is not None)
    check("浮窗可见", win._overlay is not None and win._overlay.isVisible(),
          "浮窗被回收或未显示")
    check("播放中播放按钮禁用", not win.btn_play.isEnabled())

    # 等待倒计时结束（最多 5 秒）
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not started:
        app.processEvents()
        time.sleep(0.02)
    check("倒计时结束后自动进入演奏", bool(started), "浮窗可能被提前回收")
    check("演奏状态为 running", win.player is not None and win._playing)

    # —— 暂停冻结回归：手动暂停后时间轴必须完全停止 ——
    win._on_pause()
    time.sleep(0.2)
    check("手动暂停生效", win._paused and win.btn_pause.text() == "▶ 继续")
    frozen_at = win.sld_progress.value()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check("暂停后进度冻结", win.sld_progress.value() == frozen_at,
          f"{frozen_at} -> {win.sld_progress.value()}")

    win._on_pause()  # 恢复
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and win.sld_progress.value() <= frozen_at:
        app.processEvents()
        time.sleep(0.02)
    check("恢复后继续推进", win.sld_progress.value() > frozen_at,
          f"{frozen_at} -> {win.sld_progress.value()}")

    # 停止并确认线程收尾
    win._on_stop()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and win.player is not None:
        app.processEvents()
        time.sleep(0.02)
    check("停止后恢复待命", not win._playing and win.player is None)
    check("播放按钮恢复可用", win.btn_play.isEnabled())
    check("浮窗已清理", win._overlay is None)

    mw.KeySender = sent
    win.close()
    print(f"\n全部通过：{PASS} 项检查")
    QTimer.singleShot(0, app.quit)


if __name__ == "__main__":
    main()
