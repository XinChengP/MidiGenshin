"""前台自动演奏引擎：SendInput 扫描码、高精度计时、F8 急停、暂停/焦点保护。

仅向当前前台窗口发送键盘事件；不含任何后台消息、内存注入或反检测设计。
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import defaultdict
from ctypes import wintypes

from .keys import KEYS
from .mapper import HOLD_TAP, LyreEvent

user32 = ctypes.WinDLL("user32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)

VK_F8 = 0x77
CORRECTIVE_GAP = 0.002   # 同键重按前强制提前松开的提前量
SPIN_WINDOW = 0.004      # 最后 4ms 用自旋等待保证精度
COARSE_SLEEP = 0.002


# ---------------- SendInput ----------------

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_INPUT_KEYBOARD = 1
_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002


def send_key(scan: int, up: bool) -> bool:
    """发送单个按键（扫描码方式，前台窗口接收）。返回是否成功注入。"""
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki = _KEYBDINPUT(0, scan, _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if up else 0),
                          0, None)
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1


def is_f8_pressed() -> bool:
    return bool(user32.GetAsyncKeyState(VK_F8) & 0x8000)


def get_foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


# ---------------- 动作表构建 ----------------

class Action:
    __slots__ = ("time", "kind", "keys", "event_idx")

    def __init__(self, time: float, kind: str, keys: tuple[str, ...], event_idx: int | None):
        self.time = time
        self.kind = kind          # "down" / "up"
        self.keys = keys
        self.event_idx = event_idx


def build_actions(events: list[LyreEvent], speed: float, hold_mode: str) -> list[Action]:
    """事件 -> (down/up) 动作表；保证同键先松后按、组合内按键同刻发出。

    速度只缩放事件间隔（与跟随音符时长）；短按保持时长不缩放。
    """
    if speed <= 0:
        raise ValueError("演奏速度必须大于 0")
    downs: list[tuple[float, int, list[str]]] = []
    ups: list[tuple[float, str]] = []
    for idx, ev in enumerate(events):
        t_down = ev.time / speed
        downs.append((t_down, idx, [k.key for k in ev.keys]))
        for mk, release in zip(ev.keys, ev.releases):
            if hold_mode == HOLD_TAP:
                t_up = t_down + release          # 短按：不随速度缩放
            else:
                t_up = (ev.time + release) / speed  # 跟随音符：等比缩放
            ups.append((t_up, mk.key))

    # 同键冲突：按时间归并（同时刻先 up 后 down），按下时仍处于按住则插入提前松开
    per_key: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for t, key in ups:
        per_key[key].append((t, "up"))
    for t, _, keys in downs:
        for key in keys:
            per_key[key].append((t, "down"))

    fixed_downs: list[tuple[float, str]] = []
    fixed_ups: list[tuple[float, str]] = []
    for key, ops in per_key.items():
        ops.sort(key=lambda x: (x[0], 0 if x[1] == "up" else 1))
        last_down = -1e9
        held = False
        for t, kind in ops:
            if kind == "down":
                if held:  # 仍在按住：在本次按下前强制插入松开
                    fixed_ups.append((min(max(t - CORRECTIVE_GAP, last_down + 0.001),
                                          t - 0.0005), key))
                fixed_downs.append((t, key))
                last_down, held = t, True
            else:
                if held:
                    fixed_ups.append((t, key))
                    held = False
                # 未按住的多余 up 直接丢弃

    # 合并成动作：同刻 up 先于 down；down 按 (时间, 事件序号) 稳定
    actions: list[Action] = []
    down_groups: dict[tuple[float, int], list[str]] = {}
    down_idx: dict[float, int] = {}
    for (t, idx, keys) in downs:
        down_idx[t] = idx
    for (t, key) in fixed_downs:
        idx = down_idx.get(t, -1)
        bucket = down_groups.setdefault((t, idx), [])
        bucket.append(key)
    for (t, idx), keys in down_groups.items():
        actions.append(Action(t, "down", tuple(keys), idx))
    up_groups: dict[float, list[str]] = {}
    for (t, key) in fixed_ups:
        up_groups.setdefault(t, []).append(key)
    for t, keys in up_groups.items():
        actions.append(Action(t, "up", tuple(keys), None))

    actions.sort(key=lambda a: (a.time, 0 if a.kind == "up" else 1))
    return actions


# ---------------- 演奏线程 ----------------

class KeySender:
    """按键发送器。dry_run=True 时仅记录（用于自检/测试）。"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.log: list[tuple[float, str, str]] = []  # (相对时刻, kind, key)
        self.failed_sends = 0
        self._t0 = time.perf_counter()

    def _rel(self) -> float:
        return time.perf_counter() - self._t0

    def down(self, key: str) -> bool:
        self.log.append((self._rel(), "down", key))
        if self.dry_run:
            return True
        ok = send_key(KEYS[key].scan, up=False)
        if not ok:
            self.failed_sends += 1
        return ok

    def up(self, key: str) -> bool:
        self.log.append((self._rel(), "up", key))
        if self.dry_run:
            return True
        ok = send_key(KEYS[key].scan, up=True)
        if not ok:
            self.failed_sends += 1
        return ok


class Player(threading.Thread):
    """在独立线程中按动作表演奏。回调均从演奏线程调用，GUI 需自行 marshalling。"""

    def __init__(
        self,
        actions: list[Action],
        sender: KeySender,
        *,
        on_progress=None,                 # fn(event_idx: int)
        on_state=None,                    # fn(state: str, detail: str)
        focus_guard_hwnd: int | None = None,  # 演奏中切回该窗口则自动暂停
        time_scale_check: bool = True,
    ):
        super().__init__(daemon=True, name="lyre-player")
        self.actions = actions
        self.sender = sender
        self.on_progress = on_progress
        self.on_state = on_state
        self.focus_guard_hwnd = focus_guard_hwnd

        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._pause_reason = "manual"   # manual=手动 / focus=切回本工具自动暂停
        self._origin = 0.0
        self._state = "ready"
        self._held: list[str] = []
        self._fg_away = True       # 焦点保护：前台曾离开过本窗口
        self._focus_check_counter = 0
        self._time_scale_check = time_scale_check

    # ---- 供 GUI 调用的控制 ----
    def pause(self):
        self._pause_reason = "manual"
        self._pause_evt.set()

    def resume(self):
        self._pause_evt.clear()
        # 恢复时重建焦点基线：以当前前台为准，避免"继续后立刻又被自动暂停"
        if self.focus_guard_hwnd is not None:
            self._fg_away = get_foreground_hwnd() != self.focus_guard_hwnd

    def stop(self):
        self._stop_evt.set()
        self._pause_evt.clear()

    # ---- 内部 ----
    def _set_state(self, state: str, detail: str = ""):
        self._state = state
        if self.on_state:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    def _release_all(self):
        for key in self._held:
            self.sender.up(key)
        self._held = []

    def _check_abort_keys(self) -> bool:
        """返回 True 表示需要终止。"""
        if is_f8_pressed():
            self._stop_evt.set()
            self._set_state("aborted", "hotkey")
            return True
        return False

    def _check_focus(self):
        if self.focus_guard_hwnd is None or self._pause_evt.is_set():
            return
        self._focus_check_counter += 1
        if self._focus_check_counter % 25 != 0:  # 约 50ms 一次
            return
        if get_foreground_hwnd() == self.focus_guard_hwnd:
            if self._fg_away:  # 边沿触发：离开过又切回来才暂停
                self._fg_away = False
                self._pause_reason = "focus"
                self._pause_evt.set()
        else:
            self._fg_away = True

    def _wait_until(self, target: float) -> bool:
        """等到演奏时间轴的 target 秒。返回 False 表示终止。"""
        while not self._stop_evt.is_set():
            if self._check_abort_keys():
                return False
            self._check_focus()
            if self._stop_evt.is_set():
                return False
            if self._pause_evt.is_set():
                if self._held:
                    self._release_all()
                if self._state != "paused":  # 避免每个循环重复发信号
                    self._set_state("paused", self._pause_reason)
                # 焦点自动暂停：用户切回游戏（前台离开本工具）则自动恢复，无需点按钮
                if (self._pause_reason == "focus" and self.focus_guard_hwnd is not None
                        and get_foreground_hwnd() != self.focus_guard_hwnd):
                    self._pause_evt.clear()
                    self._fg_away = True   # 已离开本工具，下次切回可再次触发保护
                time.sleep(0.02)
                continue
            if self._state == "paused":  # 刚恢复：重置时间原点
                self._origin = time.perf_counter() - target
                self._set_state("running")
            now = time.perf_counter() - self._origin
            remaining = target - now
            if remaining <= 0:
                return True
            if remaining > SPIN_WINDOW:
                time.sleep(min(COARSE_SLEEP, remaining - SPIN_WINDOW))
            # 最后几毫秒自旋（循环顶部仍有急停/焦点检查）
        return False

    # ---- 线程主体 ----
    def run(self):
        # 焦点保护基线：以开始演奏那一刻的前台为准。
        # 若开始时前台就是本工具（未切换窗口），先记录"未离开过"，
        # 等真正离开过再切回时才触发自动暂停，避免一开始就自我暂停。
        if self.focus_guard_hwnd is not None:
            self._fg_away = get_foreground_hwnd() != self.focus_guard_hwnd
        if self._time_scale_check:
            winmm.timeBeginPeriod(1)
            try:
                self._run_loop()
            finally:
                winmm.timeEndPeriod(1)
        else:
            self._run_loop()

    def _run_loop(self):
        self._origin = time.perf_counter()
        self._set_state("running")
        consecutive_fail = 0
        for action in self.actions:
            if not self._wait_until(action.time):
                break
            if action.kind == "down":
                for key in action.keys:
                    if not self.sender.down(key):
                        consecutive_fail += 1
                    else:
                        consecutive_fail = 0
                    self._held.append(key)
                if consecutive_fail >= 10:
                    self._release_all()
                    self._set_state("error", "按键发送失败：目标程序可能以管理员运行，"
                                             "请以管理员身份重新启动本工具")
                    return
                if self.on_progress and action.event_idx is not None:
                    try:
                        self.on_progress(action.event_idx)
                    except Exception:
                        pass
            else:
                for key in action.keys:
                    self.sender.up(key)
                self._held = [k for k in self._held if k not in action.keys]
        self._release_all()
        if not self._stop_evt.is_set():
            self._set_state("finished")
        elif self._state not in ("aborted", "error"):
            self._set_state("stopped")
