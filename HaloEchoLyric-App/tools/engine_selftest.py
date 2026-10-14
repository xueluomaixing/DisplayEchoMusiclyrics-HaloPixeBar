# -*- coding: utf-8 -*-
"""引擎纯函数自测（不碰硬件、不需要 GUI）。

运行:  .venv\\Scripts\\python tools\\engine_selftest.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from halo import hid as H            # noqa: E402
from halo import engine as E         # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print("%s %-44s %r" % ("[OK]  " if ok else "[FAIL]", name, got))
    if not ok:
        print("        期望: %r" % (want,))
        FAILED.append(name)


def main():
    print("=== 协议包 ===")
    pkt = H.build_text("测试")
    check("文本包长度 64", len(pkt), 64)
    check("报告 ID = 0x2E", pkt[0], 0x2E)
    check("总长字段 = 8", pkt[5] | (pkt[6] << 8), 8)
    check("文本长 = 6", pkt[7], 6)
    check("文本内容", bytes(pkt[8:14]).decode("utf-8"), "测试")
    check("校验和 = 222", pkt[14], 222)
    check("超长中文按字节截断", len(H.build_text("测" * 40)) , 64)

    lay = H.build_layout("scroll_right_to_left", (255, 255, 255))
    check("布局包头", H.to_hex(bytes(lay[:6])), "2eaaecef0009")
    check("布局 sub/mode", (lay[12], lay[13]), (0x01, 0x01))
    check("布局校验和 = 0x8F", lay[15], 0x8F)

    ui = H.build_ui_mode("clock")
    check("UI 模式 payload 类型", ui[6], 0x02)
    check("UI 模式值", ui[12], 0x00)

    light = H.build_ambient_light("dynamic", (1, 2, 3), "high", 10)
    check("氛围灯命令字节", H.to_hex(bytes(light[:4])), "2eaaec6b")
    check("氛围灯 effect", light[6], 0x13)
    check("氛围灯 = effect6", light[7], 6)

    print()
    print("=== 文本排版 ===")
    check("全角宽度", E.display_width("你好"), 4)
    check("半角宽度", E.display_width("abcd"), 4)
    pages = E.split_pages("一二三四五六七八九十", 8)
    check("切页数量", len(pages), 3)
    check("切页无损", "".join(pages), "一二三四五六七八九十")
    check("截断到 8 列", E.cut_to_columns("一二三四五六七八九十", 8), "一二三四")

    print()
    print("=== 时间轴（真实数据回归）===")
    fixture = os.path.join(HERE, "fixtures", "real_state.json")
    if os.path.exists(fixture):
        with open(fixture, "r", encoding="utf-8") as fh:
            real = json.load(fh)
        lines = real["lines"]
        starts = E.line_starts_ms(real, lines, "auto")
        check("秒 -> 毫秒换算", int(starts[-1]), int(lines[-1]["s"] * 1000))
        idx = E.current_line_index(real, real["currentTime"] * 1000, "auto")
        check("命中插件给的当前行", idx, real["currentIndex"])
        ms_lines = [{"t": l["t"], "s": l["s"] * 1000} for l in lines]
        ms_state = dict(real, lines=ms_lines)
        check("毫秒输入也认", E.current_line_index(ms_state, real["currentTime"] * 1000, "auto"),
              real["currentIndex"])
        zero = {"duration": 100.0, "currentIndex": 2,
                "lines": [{"t": "a", "s": 0}, {"t": "b", "s": 0}, {"t": "c", "s": 0}]}
        check("无时间戳时听 currentIndex", E.current_line_index(zero, 5000, "auto"), 2)
    else:
        print("[SKIP] 缺少 tools/fixtures/real_state.json")

    print()
    print("=== 播放位置推算 ===")
    import time
    st = {"currentTime": 10.0, "isPlaying": True, "playbackRate": 1.0,
          "updatedAt": (time.time() - 2.0) * 1000.0, "duration": 100.0, "lyricOffset": 0}
    pos = E.estimated_position_ms(st, time.time())
    check("播放中向前推算约 2 秒", 11000 <= pos <= 12600, True)
    st["isPlaying"] = False
    check("暂停时不推算", E.estimated_position_ms(st, time.time()), 10000.0)

    print()
    if FAILED:
        print("失败 %d 项：%s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
