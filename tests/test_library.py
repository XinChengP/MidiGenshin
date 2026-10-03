"""曲库功能测试：批量添加 / 文件夹导入 / 切换 / 移除 / 坏文件容忍。

运行：python tests/test_library.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow()
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

        print(f"\n全部通过：{PASS} 项检查")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        win.close()


if __name__ == "__main__":
    main()
