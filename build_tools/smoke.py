"""打包后自检：启动 exe，等它画出界面，再确认窗口不假死。

跑法（用打包环境里的 Python）：
    python build_tools/smoke.py dist/简黑板.exe

判断依据：
  1. 能枚举到窗口，且标题里有「简黑板」
  2. IsHungAppWindow 为假（Windows 对无响应的窗口会置这个标记）
  3. 窗口截图不是一片纯色（说明界面真画出来了，不是白屏）
  4. 没有生成 crash.log
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

APP_ID = "CleanBlackboard"


def crash_log() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_ID / "crash.log"


def find_window(keyword: str, timeout: float = 60.0) -> int:
    """轮询找窗口，给冷启动（单文件解包）留足时间。"""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if keyword in buf.value:
            found.append(hwnd)
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        found.clear()
        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.5)
    return 0


def hung(hwnd: int) -> bool:
    return bool(user32.IsHungAppWindow(hwnd))


def color_stats(hwnd: int) -> tuple[int, int, int]:
    """截窗口，返回 (不同颜色数, 像素总数, 深色像素占比%)。

    只看颜色数不够：窗口白屏也是一堆白。再看深色像素，
    有文字/图标才说明界面真的画出来了。
    """
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return 0, 0, 0.0

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, bmp)
    # PW_RENDERFULLCONTENT = 2，这样 WebView2 的内容才截得到
    user32.PrintWindow(hwnd, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h  # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    colors = set()
    data = buf.raw
    total = 0
    dark = 0
    step = 4 * 3  # 每 3 个像素抽一个，够抽样也不慢
    for i in range(0, len(data) - 3, step):
        b, g, r = data[i], data[i + 1], data[i + 2]
        colors.add(data[i : i + 3])
        total += 1
        if (r * 299 + g * 587 + b * 114) / 1000 < 110:
            dark += 1

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return len(colors), w * h, (dark / total * 100) if total else 0.0


def main() -> int:
    exe = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/简黑板.exe").resolve()
    if not exe.exists():
        print(f"找不到 {exe}")
        return 2

    log = crash_log()
    before = log.stat().st_mtime if log.exists() else 0

    print(f"启动 {exe.name} ...")
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    try:
        hwnd = find_window("简黑板")
        if not hwnd:
            print("✗ 没等到窗口")
            return 1
        print(f"✓ 窗口已出现 hwnd={hwnd}")

        # Windows 要等 UI 线程 5 秒没抽消息才打「未响应」标记，
        # 所以这里必须等够 7 秒再采样，早采样会把假死漏过去。
        print("  · 等 7 秒（跨过 Windows 的假死判定阈值）")
        time.sleep(7)

        states = []
        for _ in range(8):
            states.append(hung(hwnd))
            time.sleep(0.4)
        if any(states):
            print(f"✗ 窗口假死（IsHungAppWindow 采样 {states}）")
            return 1
        print("✓ 窗口响应正常（连续 8 次采样均未假死）")

        colors, pixels, dark = color_stats(hwnd)
        print(f"✓ 截图分析：{colors} 种颜色 / {pixels} 像素 / 深色 {dark:.1f}%")
        if colors < 40:
            print("✗ 画面颜色太单一，界面可能没渲染出来")
            return 1
        if dark < 0.05:
            print("✗ 找不到文字像素，可能是白屏")
            return 1

        if log.exists() and log.stat().st_mtime > before:
            print("✗ 生成了新的 crash.log：")
            print(log.read_text(encoding="utf-8", errors="replace")[-1500:])
            return 1
        print("✓ 没有崩溃日志")
        print("\n自检通过")
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
