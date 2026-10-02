"""暂停功能复现测试：暂停后时间轴必须完全停止。

运行：python tests/test_pause.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genshin_lyre.mapper import LyreEvent, MappedKey
from genshin_lyre.player import KeySender, Player, build_actions


def downs(sender) -> list[float]:
    return [t for t, kind, key in sender.log if kind == "down"]


def main():
    # 100 个事件，间隔 100ms（总 10 秒）
    events = [LyreEvent(time=i * 0.1, keys=[MappedKey("A", 60, False)],
                        releases=[0.060]) for i in range(100)]
    acts = build_actions(events, 1.0, "tap")
    sender = KeySender(dry_run=True)
    states = []
    p = Player(acts, sender, on_state=lambda s, d: states.append(s))
    p.start()

    time.sleep(0.5)
    n_before = len(downs(sender))
    print(f"暂停前：已发送 {n_before} 个 down")

    p.pause()
    time.sleep(0.2)   # 给线程时间进入暂停状态
    n_at_pause = len(downs(sender))
    print(f"暂停生效时：{n_at_pause} 个 down")

    time.sleep(1.0)   # 暂停期间静置 1 秒
    n_frozen = len(downs(sender))
    print(f"暂停 1 秒后：{n_frozen} 个 down（期望与上一行相同）")
    if n_frozen != n_at_pause:
        print(f"!!! 暂停失效：1 秒内多发了 {n_frozen - n_at_pause} 个 down")
        tail = downs(sender)[n_at_pause:n_frozen]
        print("!!! 新增 down 时刻:", [f"{t:.3f}" for t in tail[:10]])

    p.resume()
    time.sleep(0.5)
    n_after = len(downs(sender))
    print(f"恢复 0.5 秒后：{n_after} 个 down（应继续增加）")

    p.stop()
    p.join(timeout=5)

    ok = n_frozen == n_at_pause and n_after > n_frozen
    print("\n结论:", "暂停功能正常" if ok else "复现了暂停失效")
    print("状态序列:", states)


if __name__ == "__main__":
    main()
