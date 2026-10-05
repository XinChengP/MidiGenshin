"""曲库功能测试：批量添加 / 文件夹导入 / 切换 / 移除 / 坏文件容忍。

运行：python tests/test_library.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

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
    QSettings("XinChengP/Test", "MidiGenshin").clear()  # 清掉上轮残留（需在无窗口句柄时执行）
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(settings_org="XinChengP/Test")
    win.show()

    tmp = tempfile.mkdtemp(prefix="lyre_lib_")
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        demo = os.path.join(root, "examples", "demo.mid")
        a = os.path.join(tmp, "a.mid")
        b = os.path.join(tmp, "b.mid")
        sub = os.path.join(tmp, "sub")
        os.makedirs(sub, exist_ok=True)
        c = os.path.join(sub, "c.mid")
        m1 = os.path.join(tmp, "m.mid")
        m2 = os.path.join(sub, "m.mid")
        shutil.copy(demo, a)
        shutil.copy(demo, b)
        shutil.copy(demo, c)
        shutil.copy(demo, m1)
        shutil.copy(demo, m2)
        bad = os.path.join(tmp, "bad.mid")
        with open(bad, "wb") as f:
            f.write(b"this is not a midi file")

        # 1) 单文件加载（load_file 兼容）
        win.load_file(a)
        check("加载后曲库 1 首", len(win._library) == 1 and win._current_idx == 0)
        check("combo 1 项", win.cmb_library.count() == 1)

        # 2) 批量添加（含坏文件与重复）
        added, errors = win._add_paths([a, b, bad])
        check("去重后新增 1 首", len(added) == 1 and win._library[added[0]]["path"] == b)
        check("坏文件报错 1 条", len(errors) == 1 and "bad.mid" in errors[0])
        check("曲库 2 首", len(win._library) == 2)

        # 3) 文件夹导入（递归 + 去重 + 重名标注）
        added, errors = win._add_paths([tmp])
        check("文件夹递归发现 3 首新曲", len(added) == 3, str(len(added)))
        check("曲库 5 首", len(win._library) == 5)
        names = [e["name"] for e in win._library]
        check("重名标注文件夹", any(" · " in n for n in names)
              and sum(n.startswith("m.mid") or n.startswith("m · ") for n in names) == 2,
              str(names))

        # 4) 切换
        idx_c = next(i for i, e in enumerate(win._library)
                     if os.path.abspath(e["path"]) == os.path.abspath(c))
        win._switch_current(idx_c)
        check("切换后 _path 正确", win._path == c)
        check("下拉同步", win.cmb_library.currentIndex() == idx_c)
        # 参数联动重算：切换后 result 存在
        check("切换后映射结果存在", win.result is not None and len(win.result.events) > 0)

        # 5) 上下曲循环
        win._step_library(1)
        check("下一曲循环", win._current_idx == (idx_c + 1) % len(win._library))
        win._step_library(-1)
        win._step_library(-1)
        check("上一曲循环", win._current_idx == (idx_c - 1) % len(win._library))

        # 6) 演奏中切换自动停奏（用 stub 验证停止调用）
        class _Stub:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

            def join(self, timeout=None):
                pass

        stub = _Stub()
        win.player = stub
        win._playing = True
        win._on_library_changed(0)
        check("切换时请求停止", stub.stopped)
        win._playing = False
        win.player = None
        win._switch_current(0)

        # 7) 移除当前曲目（逐个移除直到清空）
        win._remove_current()
        check("移除后曲库 4 首", len(win._library) == 4)
        check("仍处于已加载页", win.stack.currentIndex() == 1)
        while win._library:
            win._remove_current()
        check("全部移除后回到拖放页", win.stack.currentIndex() == 0
              and not win._library)

        # 8) 清理后重新单文件加载正常
        win.load_file(a)
        check("重新加载 1 首", len(win._library) == 1 and win.song is not None)

        # 8.5) 加载后自动调整（每曲独立乐器/移调；跨度≤2 八度优先两排）
        import time as _time
        from tests.make_test_midi import build_midi as _bm, eot as _eot, note as _note, tempo as _tempo

        evs = [_tempo(0, 120)]
        for i, pp in enumerate(range(60, 73)):  # 中音区 C 大调，跨度 12
            evs += _note(i * 480, 240, 0, pp)
        evs.append(_eot(13 * 480))
        narrow = os.path.join(tmp, "narrow.mid")
        with open(narrow, "wb") as f:
            f.write(_bm([evs]))

        win.load_file(narrow)
        entry = win._library[win._current_idx]
        deadline = _time.monotonic() + 15
        while _time.monotonic() < deadline and not entry.get("auto_done"):
            app.processEvents()
            _time.sleep(0.02)
        check("自动调整完成", entry.get("auto_done") is True)
        check("跨度≤2八度自动选两排", entry.get("instrument_id") == "horn",
              str(entry.get("instrument_id")))
        check("UI 同步乐器", win.cmb_instrument.currentData().id == "horn")
        check("UI 同步移调", win.spin_transpose.value() == entry.get("transpose"))
        check("自动方案零丢弃", win.result.stats.dropped == 0,
              str(win.result.stats.dropped))

        # 第二首独立参数：demo（大跨度）应选三排
        win.load_file(demo)
        entry2 = win._library[win._current_idx]
        deadline = _time.monotonic() + 15
        while _time.monotonic() < deadline and not entry2.get("auto_done"):
            app.processEvents()
            _time.sleep(0.02)
        check("大跨度自动选三排", entry2.get("instrument_id") == "lyre",
              str(entry2.get("instrument_id")))
        # 切回第一首：保持自己的两排参数
        win._switch_current(win._library.index(entry))
        check("切回保留独立参数", win.cmb_instrument.currentData().id == "horn"
              and entry.get("auto_done") is True)

        # 9.5) 连播：演奏结束自动切下一曲并开始演奏（dry-run 发送）
        import time as _t
        import genshin_lyre.main_window as _mw
        import genshin_lyre.player as _pl
        _sent = _mw.KeySender
        _mw.KeySender = lambda: _pl.KeySender(dry_run=True)
        win.chk_autoplay.setChecked(True)
        win.load_file(a)
        win._add_paths([b])
        win._switch_current(0)
        check("连播间隔默认 5 秒", win.spin_gap.value() == 5)
        # 间隔生效：1 秒后才开始下一首
        win.spin_gap.setValue(1)
        win._on_player_state("finished", "")
        check("连播切下一曲", win._current_idx == 1, str(win._current_idx))
        _time.sleep(0.4)
        app.processEvents()
        check("间隔期间未开始", not win._playing)
        deadline = _t.monotonic() + 3
        while _t.monotonic() < deadline and not win._playing:
            app.processEvents()
            _t.sleep(0.02)
        check("间隔结束后自动开始", win._playing and win.player is not None)
        if win.player:
            win._on_stop()
            win.player.join(timeout=3)
        deadline = _t.monotonic() + 3
        while _t.monotonic() < deadline and win._playing:
            app.processEvents()
            _t.sleep(0.02)
        check("连播停止后复位", not win._playing)
        _mw.KeySender = _sent
        win.chk_autoplay.setChecked(False)

        # 9.6) 演奏速度数值框与滑杆双向联动
        win.spin_speed.setValue(150)
        check("输入框 -> 滑杆", win.sld_speed.value() == 150)
        win.sld_speed.setValue(80)
        check("滑杆 -> 输入框", win.spin_speed.value() == 80)
        win.sld_speed.setValue(100)

        # 9) 持久化：新建窗口应恢复曲库与当前曲
        win._add_paths([b])
        win._switch_current(1)
        win2 = MainWindow(settings_org="XinChengP/Test")
        check("重启恢复曲库（与源窗口一致）", len(win2._library) == len(win._library),
              f"{len(win2._library)} vs {len(win._library)}")
        check("恢复当前曲指向", os.path.abspath(win2._path) == os.path.abspath(b)
              or win2._current_idx == 1)
        narrow2 = next((e for e in win2._library if e["name"].startswith("narrow")), None)
        check("每曲参数随曲库恢复", narrow2 is not None
              and narrow2.get("instrument_id") == "horn")
        win2.close()

        print(f"\n全部通过：{PASS} 项检查")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        win.close()
        QSettings("XinChengP/Test", "MidiGenshin").clear()


if __name__ == "__main__":
    main()
