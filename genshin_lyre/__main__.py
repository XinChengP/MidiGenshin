"""命令行入口：python -m genshin_lyre [--screenshot PNG] 等。

pythonw（无控制台）运行时 stdout/stderr 为 None，任何写入都会失败；
这里统一重定向到日志文件，并把致命启动错误弹窗告知，避免"双击后无响应"。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup_streams() -> str:
    """pythonw 下重定向标准流到日志文件。返回日志路径。"""
    log_path = os.path.join(os.environ.get("TEMP", APP_DIR), "genshin_lyre.log")
    if sys.stdout is None or sys.stderr is None:
        try:
            stream = open(log_path, "a", buffering=1, encoding="utf-8")
            if sys.stdout is None:
                sys.stdout = stream
            if sys.stderr is None:
                sys.stderr = stream
        except OSError:
            pass
    return log_path


def _fatal(message: str):
    """无 Qt 环境下的兜底错误弹窗（不依赖 PySide6）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message[:2000], "原琴MIDI按键生成器 启动失败", 0x10)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    log_path = _setup_streams()
    try:
        return _run(argv, log_path)
    except SystemExit:
        raise
    except BaseException:
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        sys.stderr.flush()
        _fatal("启动出错，详见日志：\n" + log_path + "\n\n" + err[-1200:])
        return 1
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass


def _run(argv: list[str] | None, log_path: str) -> int:
    parser = argparse.ArgumentParser(description="原神原琴 MIDI 按键生成器")
    parser.add_argument("file", nargs="?", help="启动时加载的 .mid 文件")
    parser.add_argument("--screenshot", metavar="PNG",
                        help="自检用：加载后截取主窗口保存为 PNG 并退出")
    parser.add_argument("--delay", type=int, default=900,
                        help="截图前的等待毫秒数（默认 900）")
    args = parser.parse_args(argv)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication(["genshin_lyre"])
    app.setApplicationName("原神原琴 MIDI 按键生成器")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    from .main_window import MainWindow
    from .theme import apply_theme
    apply_theme(app)

    win = MainWindow()
    win.show()

    if args.file:
        QTimer.singleShot(100, lambda: win.load_file(args.file))

    exit_code = 0
    if args.screenshot:
        def grab():
            os.makedirs(os.path.dirname(os.path.abspath(args.screenshot)) or ".",
                        exist_ok=True)
            if not win.grab().save(args.screenshot):
                print(f"截图保存失败：{args.screenshot}", file=sys.stderr)
            app.quit()
        QTimer.singleShot(max(args.delay, 300), grab)
        exit_code = app.exec()
        # pythonw 下进程可能因残留线程/流无法自然退出，截图自检场景直接结束
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)

    exit_code = app.exec()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
