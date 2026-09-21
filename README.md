# copy-toast · 复制提示框

按 `Ctrl+C` 后，在鼠标旁弹出一个迷你气泡，向上飘动并逐渐淡出，告诉你这次复制到底成功没有。

- **复制成功** → 绿色「复制成功」
- **复制失败** → 黄色「复制失败」

常驻系统托盘，双击即用，无控制台窗口。

## 使用

### 方式一：直接跑 exe（推荐）

双击 `dist/copy-toast.exe` 即可，无窗口、无依赖，启动后托盘里会多一个小图标。

> 首次运行 Windows 11 可能把新图标折叠进托盘溢出区（点 `^` 箭头展开才能看到）。想让它常显，把它拖到任务栏托盘区即可。

### 方式二：用 Python 跑

需要 Python 3 且**必须带 tkinter**（python.org 官方安装包默认自带）：

```
py -c "import tkinter"    检查，没报错就可用
py copy_toast.py          启动
```

或双击 `run.bat`。这种方式会带一个控制台窗口，**关掉即退出**。

### 托盘图标

| 操作 | 效果 |
| --- | --- |
| 左键单击 | 预览一次「复制成功」气泡 |
| 右键 | 菜单：预览成功 / 预览失败 / 退出 |
| 鼠标悬停 | 提示当前状态 |

### 预览气泡外观

```
py copy_toast.py --once          预览成功样式
py copy_toast.py --once --fail   预览失败样式
```

## 原理

判断"复制成功"的关键，**不是**看有没有按下 `Ctrl+C`，而是看剪贴板内容是否真的被写入：

1. 用低层键盘钩子（`WH_KEYBOARD_LL`）旁观 `Ctrl+C`。钩子只观察，并调用 `CallNextHookEx` **原样放行**，不拦截、不吞键，前台程序照常完成复制。
2. 按下后等 180ms，再用 `GetClipboardSequenceNumber()` 检查剪贴板序号有没有变化。变了 = 复制成功，没变 = 复制失败。

因此只有真正确认写入剪贴板才会报成功，不会出现"按了就说成功"的假反馈。

**为什么不用 `RegisterHotKey`**：它会把 `Ctrl+C` 独占吞掉，目标程序收不到按键，复制根本不发生；而且 `WM_HOTKEY` 会被投递到注册它的线程，消息循环在别的线程就永远收不到。两点都会导致"按了毫无反应"。

整个工具零第三方依赖：`ctypes` 调 Win32 API + `tkinter` 画气泡 + 纯 `ctypes` 调 `Shell_NotifyIcon` 做托盘。实测常驻内存约 33MB，弹过若干次提示后稳定在 36MB 左右不再增长；空闲时 CPU 接近 0。

## 自定义

配置都在 `copy_toast.py` 顶部的「配置区」：

| 常量 | 说明 | 默认值 |
| --- | --- | --- |
| `TEXT_SUCCESS` / `TEXT_FAIL` | 气泡文案 | `复制成功` / `复制失败` |
| `COLOR_SUCCESS` / `COLOR_FAIL` | 文字与描边颜色 | `#4CAF50` 绿 / `#F5C242` 黄 |
| `COLOR_BG` | 气泡底色 | `#242424` |
| `FONT_FAMILY` / `FONT_SIZE` | 字体与字号 | `Microsoft YaHei UI` / `10` |
| `PAD_X` / `PAD_Y` | 文字内边距 | `16` / `8` |
| `OFFSET_X` / `OFFSET_Y` | 气泡相对鼠标的偏移 | `14` / `14` |
| `RISE_DISTANCE` | 向上飘动的距离 | `40` |
| `TOTAL_FRAMES` / `FRAME_INTERVAL` | 动画总帧数 / 每帧间隔(ms) | `46` / `16` |
| `HOLD_FRAMES` | 前几帧保持不变透明 | `12` |
| `COPY_SETTLE_MS` | 按下后等待剪贴板写入的时间(ms) | `180` |
| `WARN_ON_MISS` | 复制失败时是否弹提示 | `True` |
| `TRAY_TOOLTIP` | 托盘图标悬停提示 | `Ctrl+C 复制提示框（左键预览，右键菜单）` |

气泡尺寸不用手调：窗口宽高由字体度量（实测文字宽高 + 内边距）自动算出来，改文案或字号会自动适配。

## 重新打包 / 改图标

改动源码后重新生成 exe：

```
py -m venv .venv
.venv/Scripts/pip install pyinstaller
.venv/Scripts/python.exe tools/build.py
```

图标由脚本绘制生成（改颜色或造型就编辑它）：

```
.venv/Scripts/pip install pillow
.venv/Scripts/python.exe tools/make_icon.py
```

图标会输出 `assets/copy_toast.ico`（含 16–256 共 10 个尺寸）和 `assets/icon_preview.png` 预览图。

## 排查问题

打包版没有控制台，崩溃和启动信息都写进日志：

```
%LOCALAPPDATA%\copy-toast\copy_toast.log
```

## 已知限制

- **终端里按 `Ctrl+C` 中断程序**也会弹一次「复制失败」，因为剪贴板确实没变。嫌吵就把 `WARN_ON_MISS` 改成 `False`。
- **以管理员身份运行的程序**（如管理员权限的编辑器）里的按键收不到，这是 Windows 的会话隔离机制。需要覆盖它的话，本工具也要以管理员身份运行。
- 部分应用（远程桌面、个别终端、Electron 应用）复制失败是静默的，这种情况能正确提示失败。

## 文件说明

```
copy_toast.py        主程序（单文件，零第三方依赖）
run.bat              用 Python 方式启动
dist/copy-toast.exe  打包好的可执行文件
assets/              托盘图标与预览图
tools/make_icon.py   生成图标
tools/build.py       打包 exe
```
