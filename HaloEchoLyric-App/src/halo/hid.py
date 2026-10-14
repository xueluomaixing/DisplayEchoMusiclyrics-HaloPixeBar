# -*- coding: utf-8 -*-
"""花再 Halo PixelBar HID 协议层。

协议来源（三个独立实现互相印证）：
  - HaloPixelToolBox / HidPacketBuilder.cs + HaloPixelDevice.cs（C#，权威）
  - HaloLyricSync / hid_packet_builder.py（Python 移植）
  - 本机实测（2026-10-14）

设备定位（实测判据）：
  VID 0x2D99 / PID 0xA106，MI_04 下两个厂商自定义集合：
    Col01 usage_page 0xFF13 —— 输出报告 ID 6，61 字节
    Col02 usage_page 0xFF14 —— 输出报告 ID 46，63 字节   <== 像素屏通道
  官方用「名称含 花再 Halo PixelBar 且 MaxInputReportLength == 64」筛选，
  63 + 1(报告 ID) = 64 正好命中；报告 ID 就是 0x2E。

包固定 64 字节（1 字节报告 ID + 63 字节数据）。

  文本   2E AA EC E8 00 | totalLen(2,LE) | textLen(1) | UTF-8 文本 | checksum | 00...
         totalLen = 1 + textLen + 1
         checksum: acc = 128; 每个文本字节 acc += b + 2; % 256

  布局   2E AA EC EF 00 09 | payload(9) | checksum | 00 | 00...
   UI     2E AA EC EF 00 09 | payload(9) | checksum | 00 | 00...
         payload = 01|02 | R G B | 00 | 01|02 | 子类型 | 模式 | FF(FF)
         checksum: acc = 124; 对 payload 每个字节 acc += b + 2; % 256

  通用   2E AA EC <cmd> | len(2,BE) | payload | checksum
         checksum: 从下标 1 起累加所有字节，取低 8 位

  布局（实测 payload[6]=sub, payload[7]=mode）：
         左对齐 00/00   居中 00/01   右对齐 00/02   拉伸 00/03
         左→右滚 01/00  右→左滚 01/01
  设备文本协议**只有横向滚动，没有上下滚动**。
"""

import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import hid
except ImportError:  # pragma: no cover
    hid = None


VENDOR_ID = 0x2D99
PRODUCT_ID = 0xA106
PRODUCT_HINT = "Halo PixelBar"

PACKET_LENGTH = 64
OUTPUT_REPORT_ID = 0x2E
MIN_OUTPUT_PAYLOAD = 63
MAX_TEXT_BYTES = 55          # 64 - 5(头) - 2(总长) - 1(文本长) - 1(校验)

TEXT_HEADER = bytes([0x2E, 0xAA, 0xEC, 0xE8, 0x00])
LAYOUT_HEADER = bytes([0x2E, 0xAA, 0xEC, 0xEF, 0x00, 0x09])

# (sub, mode)
LAYOUTS: Dict[str, Tuple[int, int]] = {
    "left": (0x00, 0x00),
    "center": (0x00, 0x01),
    "right": (0x00, 0x02),
    "stretch": (0x00, 0x03),
    "scroll_left_to_right": (0x01, 0x00),
    "scroll_right_to_left": (0x01, 0x01),
}

LAYOUT_LABELS = {
    "left": "左对齐",
    "center": "居中",
    "right": "右对齐",
    "stretch": "两端对齐",
    "scroll_left_to_right": "滚动 左→右",
    "scroll_right_to_left": "滚动 右→左",
}

UI_MODES: Dict[str, int] = {
    "clock": 0x00, "game": 0x01, "work": 0x02, "read": 0x03,
    "cats": 0x04, "dogs": 0x05, "memes": 0x06, "cyber": 0x07, "waves": 0x08,
}

UI_MODE_LABELS = {
    "clock": "时钟", "game": "游戏", "work": "工作", "read": "读书",
    "cats": "猫咪", "dogs": "狗狗", "memes": "热梗", "cyber": "赛博", "waves": "波浪",
}

# 氛围灯：effect 1-6
LIGHT_EFFECTS: Dict[str, int] = {
    "breathing": 1, "color_tide": 2, "static": 3,
    "ripple": 4, "flow": 5, "dynamic": 6,
}

LIGHT_EFFECT_LABELS = {
    "breathing": "氛围呼吸", "color_tide": "幻彩潮汐", "static": "纯色静光",
    "ripple": "炫彩涟漪", "flow": "流光逐影", "dynamic": "动态光影",
}

LIGHT_BRIGHTNESS: Dict[str, int] = {"low": 0x14, "medium": 0x28, "high": 0x3C}
LIGHT_BRIGHTNESS_LABELS = {"low": "低", "medium": "中", "high": "高"}

CMD_AMBIENT_LIGHT = 0x6B
CMD_SCREEN_COLOR = 0xEF


class HaloError(Exception):
    pass


# --------------------------------------------------------------------------
# 包构建
# --------------------------------------------------------------------------

def pad_packet(data: bytes) -> bytes:
    return data[:PACKET_LENGTH] if len(data) >= PACKET_LENGTH else data + bytes(PACKET_LENGTH - len(data))


def text_checksum(text_bytes: bytes) -> int:
    acc = 128
    for b in text_bytes:
        acc += b + 2
    return acc % 256


def payload_checksum(payload: Iterable[int]) -> int:
    acc = 124
    for b in payload:
        acc += b + 2
    return acc % 256


def edifier_checksum(packet_without_checksum: bytes) -> int:
    """通用 Edifier 包校验：从下标 1 起累加，取低 8 位。"""
    return sum(packet_without_checksum[1:]) & 0xFF


def truncate_by_bytes(text: str, limit: int = MAX_TEXT_BYTES) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", "ignore")


def build_text(text: str, limit: int = MAX_TEXT_BYTES) -> bytes:
    text = truncate_by_bytes(text, limit)
    raw = text.encode("utf-8")
    total_len = 1 + len(raw) + 1
    body = TEXT_HEADER + struct.pack("<H", total_len) + bytes([len(raw)]) + raw
    body += bytes([text_checksum(raw)])
    return pad_packet(body)


def build_layout(layout: str, color: Tuple[int, int, int] = (255, 255, 255)) -> bytes:
    sub, mode = LAYOUTS.get(str(layout).lower(), LAYOUTS["center"])
    payload = bytes([0x01, color[0] & 0xFF, color[1] & 0xFF, color[2] & 0xFF,
                     0x00, 0x02, sub, mode, 0xFF])
    return pad_packet(LAYOUT_HEADER + payload + bytes([payload_checksum(payload)]) + b"\x00")


def build_ui_mode(mode: str, color: Tuple[int, int, int] = (255, 255, 255)) -> bytes:
    code = UI_MODES.get(str(mode).lower(), UI_MODES["clock"])
    payload = bytes([0x02, color[0] & 0xFF, color[1] & 0xFF, color[2] & 0xFF,
                     0x00, 0x01, code, 0xFF, 0xFF])
    return pad_packet(LAYOUT_HEADER + payload + bytes([payload_checksum(payload)]) + b"\x00")


def build_edifier(command: int, payload: List[int]) -> bytes:
    head = bytes([0x2E, 0xAA, 0xEC, command & 0xFF,
                  (len(payload) >> 8) & 0xFF, len(payload) & 0xFF])
    body = head + bytes(b & 0xFF for b in payload)
    return pad_packet(body + bytes([edifier_checksum(body)]))


def build_ambient_light(effect: str, color: Tuple[int, int, int],
                        brightness: str = "high", speed: int = 10) -> bytes:
    payload = [0x13, LIGHT_EFFECTS.get(effect, 3),
               color[0] & 0xFF, color[1] & 0xFF, color[2] & 0xFF,
               LIGHT_BRIGHTNESS.get(brightness, 0x3C),
               max(1, min(10, int(speed)))]
    return build_edifier(CMD_AMBIENT_LIGHT, payload)


def build_ambient_power(enabled: bool) -> bytes:
    return build_edifier(CMD_AMBIENT_LIGHT, [0x00, 0x00, 0x00, 0x00, 1 if enabled else 0, 0xFF, 0xFF])


def build_screen_color(color: Tuple[int, int, int]) -> bytes:
    return build_edifier(CMD_SCREEN_COLOR, [0x03, color[0] & 0xFF, color[1] & 0xFF, color[2] & 0xFF])


def to_hex(packet: bytes) -> str:
    return packet.hex()


# --------------------------------------------------------------------------
# 报告描述符解析（只读，用于精确定位像素屏接口）
# --------------------------------------------------------------------------

def parse_report_lengths(desc: bytes) -> Dict[int, Dict[str, int]]:
    reports: Dict[int, Dict[str, int]] = {}
    report_id = 0
    size = 0
    count = 0
    i = 0
    n = len(desc)
    while i < n:
        b = desc[i]
        if b == 0xFE:
            long_size = desc[i + 1] if i + 1 < n else 0
            i += 3 + long_size
            continue
        length = b & 0x03
        length = 4 if length == 3 else length
        item_type = (b >> 2) & 0x03
        tag = (b >> 4) & 0x0F
        data = 0
        for k in range(length):
            if i + 1 + k < n:
                data |= desc[i + 1 + k] << (8 * k)
        i += 1 + length

        if item_type == 1:
            if tag == 0x7:
                size = data
            elif tag == 0x8:
                report_id = data
            elif tag == 0x9:
                count = data
        elif item_type == 0:
            key = None
            if tag == 0x8:
                key = "in"
            elif tag == 0x9:
                key = "out"
            elif tag == 0xB:
                key = "feat"
            if key:
                reports.setdefault(report_id, {"in": 0, "out": 0, "feat": 0})
                reports[report_id][key] += size * count
    return reports


@dataclass
class HidCandidate:
    path: bytes
    interface: int = -1
    usage_page: int = 0
    product: str = ""
    serial: str = ""
    output_payload: int = 0
    report_id: int = 0
    score: int = 0

    @property
    def is_screen(self) -> bool:
        return self.report_id == OUTPUT_REPORT_ID and self.output_payload >= MIN_OUTPUT_PAYLOAD

    def describe(self) -> str:
        return "Interface %s · Usage 0x%02X/0x0001 · ReportID %d · %d 字节" % (
            self.interface, self.usage_page, self.report_id, self.output_payload)


def enumerate_candidates() -> List[HidCandidate]:
    """只读枚举匹配设备的全部接口，按"是不是像素屏通道"打分排序。"""
    if hid is None:
        raise HaloError("缺少 hidapi 库")
    out: List[HidCandidate] = []
    for info in hid.enumerate():
        if info.get("vendor_id") != VENDOR_ID or info.get("product_id") != PRODUCT_ID:
            continue
        dev = hid.device()
        try:
            dev.open_path(info["path"])
        except Exception:
            try:
                dev.close()
            except Exception:
                pass
            continue

        product = ""
        serial = ""
        try:
            product = dev.get_product_string() or ""
        except Exception:
            pass
        try:
            serial = dev.get_serial_number_string() or ""
        except Exception:
            pass

        report_id, payload = 0, 0
        try:
            for rid, sizes in parse_report_lengths(dev.get_report_descriptor()).items():
                out_bytes = sizes.get("out", 0) // 8
                if out_bytes > payload:
                    payload, report_id = out_bytes, rid
        except Exception:
            pass
        finally:
            try:
                dev.close()
            except Exception:
                pass

        score = 0
        if report_id == OUTPUT_REPORT_ID:
            score += 100
        if payload >= MIN_OUTPUT_PAYLOAD:
            score += 50
        if PRODUCT_HINT.lower() in product.lower():
            score += 10

        out.append(HidCandidate(
            path=info["path"],
            interface=info.get("interface_number", -1),
            usage_page=info.get("usage_page") or 0,
            product=product,
            serial=serial,
            output_payload=payload,
            report_id=report_id,
            score=score,
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


# --------------------------------------------------------------------------
# 设备写入
# --------------------------------------------------------------------------

class HaloDevice:
    """线程安全的像素屏写入通道。"""

    def __init__(self, debug: bool = False):
        self._dev = None
        self._debug = debug
        self._lock = threading.RLock()
        self.info: Optional[HidCandidate] = None

    def open(self, path: Optional[bytes] = None) -> HidCandidate:
        if hid is None:
            raise HaloError("缺少 hidapi 库")
        with self._lock:
            if path is not None:
                dev = hid.device()
                dev.open_path(path)
                self._dev = dev
                self.info = HidCandidate(path=path, product="(指定路径)")
                return self.info

            candidates = enumerate_candidates()
            if not candidates:
                raise HaloError("未检测到设备")
            errors = []
            for cand in candidates:
                try:
                    dev = hid.device()
                    dev.open_path(cand.path)
                    self._dev = dev
                    self.info = cand
                    return cand
                except Exception as exc:  # noqa: BLE001
                    errors.append("%s -> %s" % (cand.describe(), exc))
            raise HaloError("设备存在但打不开：\n  " + "\n  ".join(errors))

    def close(self):
        with self._lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                except Exception:
                    pass
            self._dev = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    def write(self, packet: bytes) -> bool:
        with self._lock:
            if self._dev is None:
                return False
            if len(packet) != PACKET_LENGTH:
                packet = pad_packet(packet)
            try:
                n = self._dev.write(list(packet))
                if n is not None and n >= 0:
                    return True
            except Exception:
                pass
            # 回退：部分驱动要求走 Feature Report
            try:
                n = self._dev.send_feature_report(list(packet))
                return n is not None and n >= 0
            except Exception:
                return False

    # -- 语义方法 ---------------------------------------------------------
    def show_text(self, text: str) -> bool:
        return self.write(build_text(text))

    def set_layout(self, layout: str, color=(255, 255, 255)) -> bool:
        return self.write(build_layout(layout, color))

    def set_ui_mode(self, mode: str, color=(255, 255, 255)) -> bool:
        return self.write(build_ui_mode(mode, color))

    def set_ambient_light(self, effect: str, color, brightness="high", speed=10) -> bool:
        return self.write(build_ambient_light(effect, color, brightness, speed))

    def set_ambient_power(self, enabled: bool) -> bool:
        return self.write(build_ambient_power(enabled))

    def set_screen_color(self, color) -> bool:
        return self.write(build_screen_color(color))
