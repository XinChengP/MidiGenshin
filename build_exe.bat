@echo off
rem 使用 PyInstaller 打包单文件 exe（需已安装 pyinstaller）
cd /d "%~dp0"
py -3.10 -m PyInstaller --noconfirm --onefile --windowed --name "原琴MIDI按键生成器" --icon assets\lyre.ico --add-data "assets;assets" run.py
echo 打包完成：dist\原琴MIDI按键生成器.exe
pause