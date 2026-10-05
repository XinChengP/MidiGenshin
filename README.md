# 原神原琴 MIDI 按键生成器 MidiGenshin

把 MIDI 乐曲自动转换为《原神》PC 端原琴可弹的键盘按键时序：预览、导出脚本、倒计时后自动演奏。

[![tests](https://github.com/XinChengP/MidiGenshin/actions/workflows/ci.yml/badge.svg)](https://github.com/XinChengP/MidiGenshin/actions/workflows/ci.yml)
[![release](https://img.shields.io/badge/release-v1.2-34B49F)](https://github.com/XinChengP/MidiGenshin/releases)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey)

## 下载

到 [Releases](https://github.com/XinChengP/MidiGenshin/releases) 下载 `MidiGenshin.exe`——单文件绿色版（约 44MB），无需安装 Python，双击即用。

> PyInstaller 打包产物可能被部分杀软误报，可自行从源码构建（见下文）。

## 功能一览

**导入与曲库**
- 拖入多个 `.mid` / `.midi` 或**整个文件夹**（递归扫描）批量导入，也可以用「添加文件 / 添加文件夹」按钮；自动去重、坏文件跳过并提示
- 顶部曲库下拉随时切换曲目，「上一首 / 下一首」（Ctrl+←/→）循环切换，「删除本首」移出曲库
- **曲库记忆**：重启自动恢复曲库、当前曲目与每首的键位设置（失效文件自动剔除）

**自动键位调整（每曲独立）**
- 每首曲子加载时**自动选择键位布局与移调**：音域跨度 ≤ 两个八度优先使用「原琴·两排」（效果不劣于三排时），超出则用三排
- 手动微调即固化到该曲，切曲/重启互不影响；「智能移调建议」一键枚举 ±12 选丢弃最少的档位

**音符映射**
- 键位：**原琴·三排**（21 键，低 `ZXCVBNM` / 中 `ASDFGHJ` / 高 `QWERTYU`，C3–B5）与 **原琴·两排**（14 键，中/高两行，C4–B5）
- 黑键就近吸附（可改向上 / 丢弃）、超音域丢弃并分类统计（音域外 / 黑键 / 重键冲突）、和弦按容差合并为 `键1+键2`
- **音轨筛选**：多轨谱可只保留主旋律轨；MIDI 解析支持 Format 0/1、变速（BPM）精确换算、打击乐通道默认忽略

**演奏**
- 倒计时（0/3/5/10 秒，置顶浮窗）→ **仅前台**模拟按键（无内存注入 / 后台消息 / 反检测设计）
- 演奏速度 50%–200%（滑杆或直接输入数值）；按键模式默认「跟随音符时长」，可切短按 60ms
- **急停键可选 F8–F12**（全局）；暂停 / 继续；进度条拖动**跳播**；演奏中切回工具自动暂停、切回游戏自动恢复
- **连播**：演奏结束按自定义间隔（默认 5 秒）自动开始下一首
- **从指定位置开始**：预览列表右键设起点（橙色高亮），时间轴前移无空等，可随时清除

**预览与导出**
- 时序列表：和弦着色、吸附标注、时间跳转、Ctrl+C 复制选中行
- 统计面板：直击 / 吸附 / 各类丢弃、21 键使用分布、BPM 变化表、键位速查
- 导出 txt 时序脚本（v2 可含时长列，注释头含生成参数）；**拖回窗口即可回读播放**，方便分享
- 浅色 / 深色主题（状态栏 🌙 切换）、窗口尺寸记忆、关于页

## 快速上手

1. 运行程序，把 `.mid` 拖进窗口（或批量导入整个文件夹）
2. 等状态栏出现「已自动调整：原琴（X排）· 移调 ±N」——不满意再在「参数」区微调
3. 点「▶ 播放」，**倒计时期间切到原神窗口打开原琴**，倒计时结束自动演奏
4. 任意时刻按急停键停止（无按键残留）；想练某一段，在列表上右键「从这一行开始演奏」

| 快捷键 | 作用 |
|---|---|
| 急停键（默认 F8，可选 F9–F12） | 全局急停 / 取消倒计时 |
| Esc | 取消倒计时 / 停止演奏 |
| Ctrl+← / Ctrl+→ | 上一首 / 下一首 |
| Ctrl+O / Ctrl+S | 添加文件（可多选）/ 导出 |
| Ctrl+C | 复制选中的时序行 |

## 注意事项

- 演奏按键发往**当前前台窗口**：倒计时期间请切到游戏再等结束；
- 若游戏以管理员身份运行，本工具也需以管理员身份运行，否则系统（UIPI）会拦截模拟按键（工具会自动中止并提示）；
- 自动化输入可能违反游戏用户协议，**仅供单机练习，风险自负**；本工具不含任何规避检测的设计。

## 从源码运行

```bat
pip install PySide6
py -3.10 -m genshin_lyre [可选：mid 路径]
:: 或双击 启动原琴生成器.bat（自动探测 Python 3.10+）
```

打包 exe：`pip install pyinstaller` 后双击 `build_exe.bat`，产出 `dist\MidiGenshin.exe`。

**自动发版**：推送 `v*` 标签（`git tag v1.3 && git push origin v1.3`），GitHub Actions 自动打包并创建带 exe 的 Release。

## 项目结构

```
genshin_lyre/          主包：keys / midi_parser / mapper / player / exporter / widgets / main_window / theme
assets/                应用图标
examples/demo.mid      演示用 MIDI（含变速、黑键、超音域、打击乐轨）
tests/                 自动化测试与截图自检脚本
.github/workflows      CI：跑测试 + 推 v* 标签自动发 Release
```

## 测试

共 **165 项**自动化检查：核心管线 108 + 曲库联动 35 + GUI 播放 13 + 起点演奏 9。

```bat
python tests\test_pipeline.py
python tests\test_library.py
python tests\test_gui_play.py
python tests\test_start_from.py
```

实测演奏计时精度（dry-run）：事件平均误差 ≤0.4ms（验收指标 5ms）。

## 许可证

[MIT](LICENSE)
