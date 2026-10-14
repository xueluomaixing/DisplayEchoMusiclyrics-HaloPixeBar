# -*- coding: utf-8 -*-
"""开发工具：按窗口标题截图（只截该窗口区域，不涉及桌面其它内容）。

用法: python tools/window_shot.py "窗口标题" 输出.png
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time

try:
    from PIL import ImageGrab
except ImportError:
    print("需要 Pillow：.venv\\Scripts\\pip install pillow")
    raise SystemExit(1)

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]


def find(title):
    """只做精确标题匹配。

    绝不做模糊匹配 —— 否则可能抓到标题里恰好含相同字样的无关窗口，
    截到不该看的内容。
    """
    hwnd = user32.FindWindowW(None, title)
    if hwnd and user32.IsWindowVisible(hwnd):
        return hwnd
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    title, out = sys.argv[1], sys.argv[2]

    hwnd = find(title)
    if not hwnd:
        print("窗口未找到:", title)
        return 1

    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.9)

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        print("窗口尺寸异常:", w, h)
        return 1

    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    img.save(out)
    print("OK %dx%d -> %s" % (w, h, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
