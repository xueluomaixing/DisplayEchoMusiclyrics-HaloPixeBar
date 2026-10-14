# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（与界面内的 Hd 标志一致）。"""

import os
import sys

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "icon.ico")
SIZE = 256


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make(size=SIZE):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板（紫色渐变）
    c1, c2 = (124, 77, 255), (34, 211, 238)
    r = int(size * 0.22)
    for y in range(size):
        d.line([(0, y), (size, y)], fill=lerp(c1, c2, y / max(1, size - 1)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.putalpha(mask)

    # 高光
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse(
        [-int(size * 0.3), -int(size * 0.55), int(size * 0.75), int(size * 0.3)],
        fill=(255, 255, 255, 46))
    img = Image.alpha_composite(img, hl)

    # 字母 Hd
    d = ImageDraw.Draw(img)
    dark = (11, 16, 32, 255)
    w = int(size * 0.075)
    top, bot = int(size * 0.34), int(size * 0.68)
    lx, rx = int(size * 0.24), int(size * 0.44)
    d.rounded_rectangle([lx, top, lx + w, bot], radius=w // 2, fill=dark)
    d.rounded_rectangle([rx, top, rx + w, bot], radius=w // 2, fill=dark)
    mid = (top + bot) // 2
    d.rounded_rectangle([lx, mid - w // 2, rx + w, mid + w // 2], radius=w // 2, fill=dark)

    # 音符
    nx = int(size * 0.585)
    nb = int(size * 0.63)
    d.ellipse([nx - int(size * 0.055), nb, nx + int(size * 0.055), nb + int(size * 0.115)], fill=dark)
    d.rounded_rectangle([nx + int(size * 0.020), top - int(size * 0.02),
                         nx + int(size * 0.048), nb + int(size * 0.05)],
                        radius=w // 2, fill=dark)
    d.polygon([(nx + int(size * 0.048), top - int(size * 0.02)),
               (nx + int(size * 0.115), top + int(size * 0.01)),
               (nx + int(size * 0.115), top + int(size * 0.07)),
               (nx + int(size * 0.048), top + int(size * 0.04))], fill=dark)
    return img


def main():
    base = make(SIZE)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(OUT, format="ICO", sizes=sizes)
    print("已生成", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
