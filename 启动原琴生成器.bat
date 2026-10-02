@echo off
rem 原神原琴 MIDI 按键生成器 启动脚本
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3.10 -m genshin_lyre %*
    exit /b
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3.10 -m genshin_lyre %*
    exit /b
)

start "" pythonw -m genshin_lyre %*
