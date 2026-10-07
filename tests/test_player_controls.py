"""播放控制回归：双向跳播 / 暂停中跳播 / 起点定位 / 暂停保位 / 线程收尾。

由 tests/test_pipeline.py 的 main() 通过 run_checks(check) 调用；
也可单独运行：python tests/test_player_controls.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genshin_lyre.mapper import LyreEvent, MappedKey  # noqa: E402
from genshin_lyre.player import KeySender, Player, build_actions  # noqa: E402


def _actions(n: int, gap: float = 0.08):
    """n 个同键事件（tap 模式），返回动作表与事件表。"""
    events = [LyreEvent(time=i * gap, keys=[MappedKey("A", 60, False)],
                        releases=[0.060]) for i in range(n)]
    return build_actions(events, 1.0, "tap"), events


def test_seek_forward(check):
    acts, _ = _actions(120)
    sender = KeySender(dry_run=True)
    progress = []  # (相对时刻, 事件序号)
    p = Player(acts, sender, on_progress=lambda i: progress.append((time.perf_counter(), i)))
    p.start()
    time.sleep(0.4)                       # 约播放到事件 5
    seek_at = time.perf_counter()
    p.seek(60)                            # 前跳
    time.sleep(0.3)
    p.stop()
    p.join(timeout=5)
    check("前跳线程退出", not p.is_alive())
    after = [idx for t, idx in progress if t > seek_at]
    # _seek_floor 保证 seek 写入后序号 <60 的 down 全部被丢弃；
    # 残留只可能是写入瞬间正在发送的那一个事件（毫秒级竞态，至多 1 个）。
    stragglers = [i for i in after if i < 60]
    check("前跳后事件序号 >= 60（至多 1 个写入竞态残留）", len(stragglers) <= 1
          and 60 in after, str([i for _t, i in progress][-8:]))
    check("前跳后首个事件即 60", after and after[0] == 60, str(after[:5]))
    first_after = min((t for t, i in progress if i == 60), default=None)
    check("前跳立即定位（<0.5s）", first_after is not None and first_after - seek_at < 0.5)


def test_seek_backward(check):
    acts, _ = _actions(200, gap=0.05)     # 10s
    sender = KeySender(dry_run=True)
    progress = []
    p = Player(acts, sender, on_progress=lambda i: progress.append((time.perf_counter(), i)))
    p.start()
    time.sleep(0.6)                       # 约播放到事件 12
    seek_at = time.perf_counter()
    p.seek(2)                             # 回跳到已播过的事件
    time.sleep(0.3)
    p.stop()
    p.join(timeout=5)
    after = [idx for t, idx in progress if t > seek_at]
    # seek 与“当前正在等待的 down”存在毫秒级竞态：允许最多一个残留事件，
    # 但必须从事件 2 起连续重播（旧实现无法回退，2 之后不会出现）。
    from2 = after[after.index(2):] if 2 in after else []
    check("后跳后从事件 2 连续重播",
          from2 and from2 == list(range(2, 2 + len(from2))) and len(from2) >= 3,
          str(after[:8]))
    first_after = min((t for t, i in progress if t > seek_at), default=None)
    check("后跳立即定位（<0.5s）", first_after is not None and first_after - seek_at < 0.5)
    check("后跳线程退出", not p.is_alive())


def test_seek_while_paused(check):
    acts, _ = _actions(200, gap=0.05)
    sender = KeySender(dry_run=True)
    progress = []
    states = []
    p = Player(acts, sender, on_progress=lambda i: progress.append((time.perf_counter(), i)),
               on_state=lambda s, d: states.append(s))
    p.start()
    time.sleep(0.4)
    p.pause()
    time.sleep(0.15)
    paused_at = time.perf_counter()
    p.seek(30)                            # 暂停中跳播
    time.sleep(0.35)
    frozen = [i for t, i in progress if t > paused_at]
    check("暂停中跳播不发送事件", not frozen, str(frozen[:5]))
    p.resume()
    resume_at = time.perf_counter()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not any(t > resume_at for t, _i in progress):
        time.sleep(0.02)
    p.stop()
    p.join(timeout=5)
    after = [i for t, i in progress if t > resume_at]
    check("恢复后从事件 30 继续", after and after[0] == 30, str(after[:5]))
    check("暂停状态出现过", "paused" in states, str(states))


def test_start_event_idx(check):
    acts, _ = _actions(120)
    sender = KeySender(dry_run=True)
    progress = []
    p = Player(acts, sender, start_event_idx=40,
               on_progress=lambda i: progress.append((time.perf_counter(), i)))
    p.start()
    time.sleep(0.4)
    p.stop()
    p.join(timeout=5)
    check("起点前无事件", progress and progress[0][1] == 40,
          str([i for _t, i in progress][:5]))
    downs = [t for t, k, _key in sender.log if k == "down"]
    check("起点即刻发声（<0.4s）", downs and downs[0] < 0.4, f"{downs[0]:.2f}s")
    # 起点之后仍可回跳到起点之前
    p2 = Player(acts, KeySender(dry_run=True), start_event_idx=40,
                on_progress=lambda i: progress.append((time.perf_counter(), i)))
    p2.start()
    time.sleep(0.3)
    seek_at = time.perf_counter()
    p2.seek(5)
    time.sleep(0.3)
    p2.stop()
    p2.join(timeout=5)
    after = [i for t, i in progress if t > seek_at]
    check("可回跳到初始起点之前", after and after[0] == 5, str(after[:5]))


def test_pause_keeps_remaining_gap(check):
    # 间隔 1s，冻结语义：暂停不推进曲子时间轴，恢复后从暂停位置继续等剩余
    acts, _ = _actions(6, gap=1.0)
    sender = KeySender(dry_run=True)
    progress = []
    p = Player(acts, sender, on_progress=lambda i: progress.append((time.perf_counter(), i)))
    p.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(progress) < 1:
        time.sleep(0.02)
    check("首事件已播放", len(progress) >= 1)
    time.sleep(0.3)                       # 曲子走到 ≈0.3s
    p.pause()
    time.sleep(0.4)                       # 暂停 0.4s：时间轴必须冻结
    p.resume()
    resume_at = time.monotonic()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and len(progress) < 2:
        time.sleep(0.02)
    p.stop()
    p.join(timeout=5)
    check("恢复后播放第二事件", len(progress) >= 2, str(len(progress)))
    if len(progress) >= 2:
        wait = progress[1][0] - resume_at
        # 剩余 ≈ 1.0 - 0.3 = 0.7s。吞掉剩余（旧 bug）≈0；把暂停计入进度 ≈0.3
        check("冻结语义：恢复只等剩余（0.55~0.9s）", 0.55 < wait < 0.9, f"{wait:.2f}s")


def test_stop_cleanup(check):
    acts, _ = _actions(400, gap=0.02)     # 8s
    sender = KeySender(dry_run=True)
    states = []
    p = Player(acts, sender, on_state=lambda s, d: states.append(s))
    p.start()
    time.sleep(0.4)
    p.pause()
    time.sleep(0.1)
    p.stop()
    p.join(timeout=5)
    check("暂停后停止线程退出", not p.is_alive())
    downs = [x for x in sender.log if x[1] == "down"]
    ups = [x for x in sender.log if x[1] == "up"]
    check("停止后无按键残留", len(ups) >= len(downs), f"down={len(downs)} up={len(ups)}")
    check("终态恰为一次 stopped", states and states[-1] == "stopped"
          and states.count("stopped") == 1, str(states))


def run_checks(check):
    test_seek_forward(check)
    test_seek_backward(check)
    test_seek_while_paused(check)
    test_start_event_idx(check)
    test_pause_keeps_remaining_gap(check)
    test_stop_cleanup(check)


if __name__ == "__main__":
    _pass = 0

    def _check(name, cond, detail=""):
        global _pass
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
        if not cond:
            raise AssertionError(name)
        _pass += 1

    run_checks(_check)
    print(f"\n全部通过：{_pass} 项检查")
