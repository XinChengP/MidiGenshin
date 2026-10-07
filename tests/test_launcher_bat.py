# -*- coding: utf-8 -*-
"""启动脚本分支验证：用 stub pyw/py/pythonw/python 探测各分支，不打开真实 GUI。

候选顺序：pyw -3.10 / py -3.10 / pyw -3 / py -3 / pythonw / python；
全部拒绝时提示安装并退出码 1；PySide6 缺失时给出安装命令并退出码 1。
"""
import os
import subprocess
import sys
import tempfile
import time

if os.name != "nt":
    print("非 Windows 环境，跳过启动脚本验证")
    raise SystemExit(0)

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bat = os.path.join(root, "启动原琴生成器.bat")
tmp = tempfile.mkdtemp(prefix="lyre_launcher_")

STUB = """@echo off
echo CALL %*>> "%STUB_CALLS%"
if defined STUB_FAIL_ALL exit /b 1
echo %* | findstr /C:"PySide6" >nul
if not errorlevel 1 exit /b %STUB_PYSIDE_RC%
echo %* | findstr /C:"-m" >nul
if not errorlevel 1 echo %*>> "%STUB_LOG%"
exit /b 0
"""

fails = []
PASS = 0


def case(name, cond, detail=""):
    global PASS
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"  ({detail})" if not cond else ""))
    if not cond:
        fails.append(name)
    else:
        PASS += 1


def setup(stubs):
    for d in (tmp, os.path.join(tmp, "stubs")):
        os.makedirs(d, exist_ok=True)
    for name in ("pyw.cmd", "py.cmd", "pythonw.cmd", "python.cmd"):
        p = os.path.join(tmp, "stubs", name)
        if name in stubs:
            with open(p, "w", encoding="ascii") as f:
                f.write(STUB)
        elif os.path.exists(p):
            os.remove(p)


def run(env_extra, args=("--demo",)):
    env = dict(os.environ)
    env["STUB_LOG"] = os.path.join(tmp, "log.txt")
    env["STUB_CALLS"] = os.path.join(tmp, "calls.txt")
    # PATH 只留 stubs 与系统目录：真实 python/py 不得参与探测回退
    system32 = os.environ.get("SystemRoot", r"C:\Windows")
    env["PATH"] = os.pathsep.join([
        os.path.join(tmp, "stubs"),
        os.path.join(system32, "System32"),
        system32,
    ])
    env.update(env_extra)
    for f in (env["STUB_LOG"], env["STUB_CALLS"]):
        if os.path.exists(f):
            os.remove(f)
    p = subprocess.run(["cmd", "/c", bat, *args], env=env,
                       capture_output=True, timeout=30)
    log = ""
    for _ in range(60):
        if os.path.exists(env["STUB_LOG"]):
            with open(env["STUB_LOG"], encoding="utf-8", errors="replace") as f:
                log = f.read().strip()
            if log:
                break
        time.sleep(0.05)
    p.calls = ""
    if os.path.exists(env["STUB_CALLS"]):
        p.calls = open(env["STUB_CALLS"], encoding="utf-8",
                       errors="replace").read().replace("\r\n", " | ")
    return p, log


# 1) 全部 stub 可用：选 GUI 版 pyw -3.10，参数透传（直接调用，同步可见）
setup({"pyw.cmd", "py.cmd", "pythonw.cmd", "python.cmd"})
p, log = run({"STUB_PYSIDE_RC": "0"})
case("首选 pyw -3.10", p.returncode == 0 and "-3.10 -m genshin_lyre --demo" in log,
     f"rc={p.returncode} log={log!r} calls={getattr(p, 'calls', '')!r}")

# 2) 缺 PySide6：给出安装提示并失败退出
setup({"pyw.cmd"})
p, log = run({"STUB_PYSIDE_RC": "1"})
out = p.stdout.decode("utf-8", "replace")  # 脚本已 chcp 65001，输出为 UTF-8 字节
case("缺 PySide6 提示", p.returncode == 1 and "PySide6" in out and "pip install" in out,
     f"rc={p.returncode} out={out!r}")

# 3) 版本过低：全部拒绝 -> 失败退出
setup({"pyw.cmd"})
p, log = run({"STUB_FAIL_ALL": "1"})
out = p.stdout.decode("utf-8", "replace")
case("无 3.10+ 时失败退出", p.returncode == 1 and "未找到 Python" in out,
     f"rc={p.returncode} out={out!r}")

# 4) 仅控制台版可用：选 py -3.10（通过缺依赖提示验证选择）
setup({"py.cmd"})
p, log = run({"STUB_PYSIDE_RC": "1"})
out = p.stdout.decode("utf-8", "replace")
case("回退 py -3.10（提示中可见）", p.returncode == 1 and "py -3.10 -m pip install" in out,
     f"rc={p.returncode} out={out!r}")

# 5) 仅 python 可用
setup({"python.cmd"})
p, log = run({"STUB_PYSIDE_RC": "1"})
out = p.stdout.decode("utf-8", "replace")
case("回退 python（提示中可见）", p.returncode == 1 and "python -m pip install" in out,
     f"rc={p.returncode} out={out!r}")

# 6) pythonw 直接调用分支
setup({"pythonw.cmd"})
p, log = run({})
case("pythonw 直接调用", p.returncode == 0 and "-m genshin_lyre --demo" in log,
     f"rc={p.returncode} log={log!r} calls={getattr(p, 'calls', '')!r}")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'全部通过' if not fails else '失败: ' + '; '.join(fails)}：{PASS} 项检查")
raise SystemExit(1 if fails else 0)
