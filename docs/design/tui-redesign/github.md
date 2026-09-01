repo: Aiaid/pyMalbolge
branch: master
path: malbolge/

## Last sync
date: 2026-08-10T23:52:31Z

### Updated in this project
- 复刻了现有 Textual TUI 调试器（4 面板 2×4 grid + 状态栏）
- 新增两个重设计方向：信息密度最大化（工程向）与教学向大字分步
- 补充 80×24 收缩态：面板折叠为标签页 + 命令行

## Screen map
| 项目内屏幕 | 来源文件 |
|---|---|
| `Malbolge TUI.dc.html` → 0a 现状复刻 | `malbolge/debug_tui.py`, `screenshots/tui.png` |
| `Malbolge TUI.dc.html` → 1a 密度最大化 | `malbolge/debug_tui.py`, `malbolge/debugger.py` (OPCODE_HELP, disassemble, preview_next_instruction) |
| `Malbolge TUI.dc.html` → 1b 教学向 | `malbolge/debugger.py` (OPCODE_HELP, ENCRYPT 表), `README.md` (TUI keys) |
| `Malbolge TUI.dc.html` → 1c 80×24 | `malbolge/debug_tui.py` (BINDINGS, CSS grid) |
