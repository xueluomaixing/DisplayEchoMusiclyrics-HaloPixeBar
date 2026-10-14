# -*- coding: utf-8 -*-
"""设备管理：扫描、连接、断开、在线状态监测与自动重连。"""

import threading
import time
from typing import Callable, List, Optional

from . import hid as halohid
from .hid import HaloDevice, HaloError, HidCandidate

STATE_ONLINE = "online"
STATE_OFFLINE = "offline"
STATE_CONNECTING = "connecting"

STATE_LABELS = {
    STATE_ONLINE: "设备在线",
    STATE_OFFLINE: "设备未连接",
    STATE_CONNECTING: "正在连接…",
}


class DeviceManager:
    def __init__(self, cfg: dict, logger):
        self._cfg = cfg
        self._log = logger
        self._device: Optional[HaloDevice] = None
        self._state = STATE_OFFLINE
        self._last_error = ""
        self._lock = threading.RLock()
        self._connect_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_change: Optional[Callable[[dict], None]] = None

    # -- 状态 -------------------------------------------------------------
    def set_cfg(self, cfg: dict):
        self._cfg = cfg

    def status(self) -> dict:
        with self._lock:
            info = self._device.info if (self._device and self._device.info) else None
            return {
                "state": self._state,
                "label": STATE_LABELS.get(self._state, "未知"),
                "error": self._last_error,
                "connected": self._state == STATE_ONLINE,
                "info": {
                    "product": (info.product if info else "") or "花再 Halo PixelBar",
                    "serial": (info.serial if info else "") or "",
                    "vid": "0x%04X" % halohid.VENDOR_ID,
                    "pid": "0x%04X" % halohid.PRODUCT_ID,
                    "interface": info.interface if info else -1,
                    "usage_page": "0x%04X" % (info.usage_page if info else 0),
                    "report_id": info.report_id if info else 0,
                    "payload": info.output_payload if info else 0,
                    "describe": info.describe() if info else "",
                },
            }

    def _emit(self):
        if self._on_change:
            try:
                self._on_change(self.status())
            except Exception:
                pass

    def _set_state(self, state: str, error: str = ""):
        changed = False
        with self._lock:
            if state != self._state or error != self._last_error:
                self._state = state
                self._last_error = error
                changed = True
        if changed:
            self._emit()

    # -- 扫描 / 连接 -------------------------------------------------------
    def scan(self) -> List[HidCandidate]:
        """只读扫描所有匹配接口，不碰设备状态。"""
        try:
            items = halohid.enumerate_candidates()
            self._log.info("USB 扫描：发现 %d 个 Halo 接口" % len(items))
            for it in items:
                self._log.info("  %s%s" % (it.describe(), "  ← 像素屏通道" if it.is_screen else ""))
            return items
        except HaloError as exc:
            self._log.error("USB 扫描失败：%s" % exc)
            return []

    def connect(self) -> bool:
        # 串行化：自动连接线程和设备监测线程可能同时触发，避免重复连接
        with self._connect_lock:
            with self._lock:
                if self._state == STATE_ONLINE and self._device and self._device.is_open:
                    return True
            self._set_state(STATE_CONNECTING)
            dev = HaloDevice()
            try:
                info = dev.open()
            except HaloError as exc:
                dev.close()
                with self._lock:
                    self._device = None
                self._set_state(STATE_OFFLINE, str(exc))
                return False
            with self._lock:
                self._device = dev
            self._log.info("已连接 %s" % info.describe())
            self._set_state(STATE_ONLINE)
            return True

    def disconnect(self, reason: str = "手动断开"):
        dev = None
        with self._lock:
            dev = self._device
            self._device = None
        if dev:
            dev.close()
        if self._state != STATE_OFFLINE:
            self._log.info("已断开设备（%s）" % reason)
        self._set_state(STATE_OFFLINE, "" if reason == "手动断开" else reason)

    def device(self) -> Optional[HaloDevice]:
        with self._lock:
            return self._device

    def write(self, packet: bytes) -> bool:
        dev = self.device()
        if dev is None:
            self._set_state(STATE_OFFLINE, "设备未连接")
            return False
        ok = dev.write(packet)
        if not ok:
            self._log.warn("写入设备失败，标记为离线")
            self.disconnect("写入失败")
        return ok

    # -- 后台监测 ---------------------------------------------------------
    def start_watch(self, on_change: Callable[[dict], None]):
        self._on_change = on_change
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch_loop, name="device-watch", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def _watch_loop(self):
        while not self._stop.is_set():
            try:
                interval = max(1.0, float(self._cfg["device"].get("reconnect_interval_ms", 3000)) / 1000.0)

                if self._state == STATE_ONLINE:
                    if not self._still_present():
                        self.disconnect("设备已拔出")
                elif self._cfg["device"].get("auto_connect", True):
                    if self._any_present():
                        self.connect()
                    else:
                        self._set_state(STATE_OFFLINE)

                self._stop.wait(interval)
            except Exception as exc:  # noqa: BLE001
                self._log.error("设备监测异常：%s" % exc)
                self._stop.wait(3.0)

    def _any_present(self) -> bool:
        try:
            return bool(halohid.enumerate_candidates())
        except Exception:
            return False

    def _still_present(self) -> bool:
        dev = self.device()
        if dev is None or dev.info is None:
            return False
        try:
            for cand in halohid.enumerate_candidates():
                if cand.path == dev.info.path:
                    return True
        except Exception:
            return True   # 枚举失败时不要误判为拔出
        return False
