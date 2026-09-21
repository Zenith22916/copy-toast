"""
Ctrl+C 气泡反馈工具
--------------------
监听全局 Ctrl+C，在鼠标位置弹出一个向上飘动并逐渐消失的小气泡。

气泡内容极简：只显示「复制成功」（绿）或「复制失败」（黄）。
窗口尺寸按文字实际测量自适应，刚好只容下这几个字。

设计要点
  * 反馈的可靠性：不只看「按下 Ctrl+C」，而是轮询剪贴板序号（GetClipboardSequenceNumber），
    只有序号真的变化（即内容确实写进了剪贴板）才判定成功。这样能识别"按了但没复制到"。
  * 零第三方依赖：全局按键监听用 ctypes 调 Win32 低层键盘钩子（WH_KEYBOARD_LL）。
    钩子只「旁观」按键并原样放行（CallNextHookEx），不拦截、不吞键，前台程序照常收到 Ctrl+C，
    因此复制动作正常发生。不需要管理员权限。
  * 纯 tkinter 绘制：气泡用 Toplevel + 无边框 + 透明键色实现圆角胶囊和淡出。
  * 后台低占用：钩子线程只在按键时被回调，其余时间阻塞在消息循环，CPU 接近 0。

运行：
    python copy_toast.py                # 正常启动
    python copy_toast.py --once         # 调试：预览成功气泡
    python copy_toast.py --once --fail  # 调试：预览失败气泡
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

# ---------------------------------------------------------------------------
# 配置区
# ---------------------------------------------------------------------------

TEXT_SUCCESS = "复制成功"      # 成功提示文案
TEXT_FAIL = "复制失败"         # 失败提示文案
FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 10                 # 字号
PAD_X = 16                     # 文字左右内边距（像素）
PAD_Y = 8                      # 文字上下内边距（像素）
MAX_RADIUS = 8                 # 圆角半径上限；胶囊高度小于 16px 时自动取 h/2

OFFSET_X = 14                  # 气泡相对鼠标的横向偏移
OFFSET_Y = 14                  # 气泡相对鼠标的纵向偏移
RISE_DISTANCE = 40             # 气泡向上飘动的总距离（像素）
TOTAL_FRAMES = 46              # 动画总帧数
FRAME_INTERVAL = 16            # 每帧间隔（毫秒），约 60fps
HOLD_FRAMES = 12               # 前若干帧保持完全不透明，之后再开始淡出

WATCHER_INTERVAL = 25          # 剪贴板变化检测间隔（毫秒）
COPY_SETTLE_MS = 180           # 按下 Ctrl+C 后等待剪贴板写入的时间（毫秒）
CTRL_C_DEBOUNCE = 0.30         # 长按 Ctrl+C 时的去重间隔（秒）

WARN_ON_MISS = True            # 复制失败时是否弹提示。
                               # 注意：终端里按 Ctrl+C 中断程序也会触发一次「复制失败」（剪贴板没变），
                               # 如果嫌吵可以改成 False。

# 配色：深色底 + 成功绿 / 失败黄
COLOR_BG = "#242424"           # 胶囊底色
COLOR_SUCCESS = "#4CAF50"      # 复制成功：绿
COLOR_FAIL = "#F5C242"         # 复制失败：黄

# Win32 常量
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_CONTROL = 0x11
VK_C = 0x43

user32 = ctypes.WinDLL("user32", use_last_error=True)

# 显式声明签名。64 位下句柄/指针若按默认 c_int 解析会被截断，
# 必须声明为 c_void_p / 平台正确的宽度，否则会崩溃或读错内存。
HANDLE = ctypes.c_void_p
HWND_T = ctypes.c_void_p
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t

user32.GetClipboardSequenceNumber.restype = ctypes.c_uint32
user32.GetClipboardSequenceNumber.argtypes = []

user32.GetCursorPos.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]

user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, ctypes.c_void_p)

user32.SetWindowsHookExW.restype = HANDLE
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, HANDLE, ctypes.c_uint32]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [HANDLE, ctypes.c_int, WPARAM, ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = ctypes.c_int
user32.UnhookWindowsHookEx.argtypes = [HANDLE]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), HWND_T, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]


# ---------------------------------------------------------------------------
# 剪贴板 / 鼠标工具
# ---------------------------------------------------------------------------

def clipboard_sequence() -> int:
    """返回剪贴板序号，剪贴板内容每次变化该值都会 +1。"""
    return int(user32.GetClipboardSequenceNumber())


def get_cursor_pos() -> tuple[int, int]:
    """返回鼠标当前的屏幕坐标。"""
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ---------------------------------------------------------------------------
# 气泡窗口
# ---------------------------------------------------------------------------

class Toast(tk.Toplevel):
    """一个会向上飘动并淡出的迷你圆角气泡。

    尺寸不写死：用字体度量算出文字实际宽高，再加固定内边距，
    所以窗口刚好只容下文案本身。
    """

    def __init__(self, master: tk.Tk, text: str, x: int, y: int,
                 color: str = COLOR_SUCCESS):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)

        # 按文字实测尺寸决定窗口大小
        # 注意：不要用 self._w / self._h 命名——tkinter 内部用 _w 存控件路径名，
        # 覆盖它会导致后续创建子控件时报 TypeError。
        font = tkfont.Font(root=self, family=FONT_FAMILY,
                           size=FONT_SIZE, weight="bold")
        self._toast_w = font.measure(text) + PAD_X * 2
        self._toast_h = font.metrics("linespace") + PAD_Y * 2

        self._base_x = x + OFFSET_X
        self._base_y = y - OFFSET_Y - self._toast_h
        self._frame = 0
        self._closed = False

        self._build(text, color, font)

        self.geometry(f"{self._toast_w}x{self._toast_h}"
                      f"+{self._base_x}+{self._base_y}")
        self.after(FRAME_INTERVAL, self._animate)

    # -- 绘制 --------------------------------------------------------------
    def _build(self, text: str, color: str, font: tkfont.Font) -> None:
        canvas = tk.Canvas(
            self, width=self._toast_w, height=self._toast_h,
            bg="#000000", highlightthickness=0, bd=0,
        )
        canvas.pack()
        # 用黑色作透明键色，让圆角外的区域透出桌面
        self.attributes("-transparentcolor", "#000000")

        radius = min(MAX_RADIUS, self._toast_h // 2)
        # 胶囊：深色底 + 与状态同色的描边
        self._round_rect(canvas, 1, 1, self._toast_w - 1, self._toast_h - 1,
                         radius, fill=COLOR_BG, outline=color, width=1)
        canvas.create_text(self._toast_w / 2, self._toast_h / 2, text=text,
                           fill=color, font=font)

    @staticmethod
    def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                    r: float, **kwargs) -> int:
        """在 Canvas 上画一个圆角矩形（用多边形平滑拟合圆角）。"""
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    # -- 动画 --------------------------------------------------------------
    def _animate(self) -> None:
        if self._closed:
            return
        self._frame += 1
        if self._frame > TOTAL_FRAMES:
            self._destroy()
            return

        progress = self._frame / TOTAL_FRAMES
        # 位移：先快后慢（ease-out），飘起来更自然
        eased = 1 - (1 - progress) ** 2
        dy = int(RISE_DISTANCE * eased)
        self.geometry(f"{self._toast_w}x{self._toast_h}"
                      f"+{self._base_x}+{self._base_y - dy}")

        if self._frame <= HOLD_FRAMES:
            alpha = 1.0
        else:
            fade = (self._frame - HOLD_FRAMES) / max(1, TOTAL_FRAMES - HOLD_FRAMES)
            alpha = max(0.0, 1.0 - fade)
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            pass

        self.after(FRAME_INTERVAL, self._animate)

    def _destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# 全局按键监听：低层键盘钩子
# ---------------------------------------------------------------------------

class KeyboardWatcher:
    """用 WH_KEYBOARD_LL 低层键盘钩子旁观 Ctrl+C。

    关键点：
      * 钩子只观察，不拦截——回调里必须调 CallNextHookEx 放行，
        否则 Ctrl+C 会被吞掉，前台程序收不到，复制根本不会发生。
      * 钩子必须安装在「有消息循环的线程」上：系统把按键事件投递到安装钩子的那个线程，
        所以这里起一个专门的线程装钩子并跑 GetMessageW 循环。
      * 回调在钩子线程里执行，不能碰 tkinter，只往线程安全队列塞事件。
    """

    def __init__(self, event_queue: queue.Queue) -> None:
        self._queue = event_queue
        self._hook = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._last_hit = 0.0
        # 必须持有引用，否则回调对象被回收会导致崩溃
        self._proc = HOOKPROC(self._callback)

    # -- 回调 --------------------------------------------------------------
    def _callback(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.vkCode == VK_C and (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000):
                now = time.monotonic()
                # 长按会产生连续 keydown，做一次去重
                if now - self._last_hit > CTRL_C_DEBOUNCE:
                    self._last_hit = now
                    self._queue.put(("ctrl_c", True))
        # 原样放行，绝不能吞掉按键
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    # -- 线程 --------------------------------------------------------------
    def _loop(self) -> None:
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook:
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def start(self, timeout: float = 2.0) -> bool:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="keyboard-hook")
        self._thread.start()
        self._ready.wait(timeout=timeout)
        return bool(self._hook)

    def stop(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------

class CopyToastApp:
    """驻留后台的应用：监听全局 Ctrl+C，触发气泡。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()          # 主窗口不显示，只当动画宿主
        self.queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._last_seq = clipboard_sequence()
        self._pending = False         # 已按下 Ctrl+C，正在等剪贴板写入
        self.watcher = KeyboardWatcher(self.queue)
        self._hook_ok = False

    # -- 剪贴板轮询 --------------------------------------------------------
    def watch_clipboard(self) -> None:
        """轮询剪贴板序号：变化即代表内容确实被写入了。"""
        seq = clipboard_sequence()
        if seq != self._last_seq:
            self._last_seq = seq
            self._pending = False     # 已确认写入，取消失败判定
            self._emit(success=True)
        self.root.after(WATCHER_INTERVAL, self.watch_clipboard)

    # -- 队列处理 ----------------------------------------------------------
    def drain_queue(self) -> None:
        """在主线程消费事件队列（tkinter 只能在主线程操作）。"""
        try:
            while True:
                kind, _ = self.queue.get_nowait()
                if kind == "ctrl_c":
                    self._pending = True
                    self.root.after(COPY_SETTLE_MS, self._resolve_pending)
        except queue.Empty:
            pass
        self.root.after(20, self.drain_queue)

    def _resolve_pending(self) -> None:
        """按下 Ctrl+C 且给足写入时间后，剪贴板仍没变 → 判定复制失败。"""
        if not self._pending:
            return
        self._pending = False
        if not WARN_ON_MISS:
            return
        self._emit(success=False)

    # -- 弹出气泡 ----------------------------------------------------------
    def _emit(self, success: bool) -> None:
        text = TEXT_SUCCESS if success else TEXT_FAIL
        color = COLOR_SUCCESS if success else COLOR_FAIL
        x, y = get_cursor_pos()
        try:
            Toast(self.root, text, x, y, color=color)
        except tk.TclError:
            pass

    # -- 启动 --------------------------------------------------------------
    def run(self) -> None:
        self._hook_ok = self.watcher.start()
        self.watch_clipboard()
        self.drain_queue()
        if self._hook_ok:
            mode = "低层键盘钩子（原样放行 Ctrl+C）"
        else:
            mode = "钩子安装失败，已降级为纯剪贴板监听（右键复制等仍会提示）"
        print(f"[copy-toast] 已启动：{mode}")
        print("[copy-toast] 按 Ctrl+C 试试，关闭窗口即可退出。")
        try:
            self.root.mainloop()
        finally:
            self.watcher.stop()


def _preview(success: bool = True) -> None:
    """调试用：只弹一个气泡，方便预览外观。"""
    root = tk.Tk()
    root.withdraw()
    x, y = get_cursor_pos()
    Toast(root, TEXT_SUCCESS if success else TEXT_FAIL, x, y,
          color=COLOR_SUCCESS if success else COLOR_FAIL)
    root.after(TOTAL_FRAMES * FRAME_INTERVAL + 200, root.destroy)
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ctrl+C 气泡反馈工具")
    parser.add_argument("--once", action="store_true", help="只弹一个气泡用于预览外观")
    parser.add_argument("--fail", action="store_true", help="配合 --once，预览失败样式")
    args = parser.parse_args()

    if args.once:
        _preview(success=not args.fail)
        return 0

    CopyToastApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
