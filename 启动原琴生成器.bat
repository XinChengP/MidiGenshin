@echo off
chcp 65001 >nul
rem 原神原琴 MIDI 按键生成器 启动脚本：探测 Python 3.10+ 与 PySide6 后启动
rem 注意：调用外部批处理必须用 call 前缀，否则控制权转移会终止本脚本
setlocal EnableExtensions
cd /d "%~dp0"
set "LC="

call pyw -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=pyw -3.10"
if not defined LC call py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=py -3.10"
if not defined LC call pyw -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=pyw -3"
if not defined LC call py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=py -3"
if not defined LC call pythonw -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=pythonw"
if not defined LC call python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "LC=python"

set "PYOK="
if defined LC call %LC% -c "import PySide6" >nul 2>nul && set "PYOK=1"

if not defined LC echo [启动失败] 未找到 Python 3.10 或更高版本。
if not defined LC echo 请安装 Python 3.10+，并勾选 "Add to PATH"。 https://www.python.org/downloads/
if not defined LC echo 或使用免安装的 release 版： https://github.com/XinChengP/MidiGenshin/releases
if defined LC if not defined PYOK echo [启动失败] 已找到 Python，但缺少依赖 PySide6。
if defined LC if not defined PYOK echo 请执行下方命令安装后重试： %LC% -m pip install PySide6

if defined PYOK (
    %LC% -m genshin_lyre %*
    exit /b 0
)
exit /b 1
