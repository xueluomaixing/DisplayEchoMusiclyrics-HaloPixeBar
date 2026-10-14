# -*- coding: utf-8 -*-
"""歌词引擎：从 EchoMusic 插件取数据，按显示策略渲染并写入像素屏。

时间戳单位与定位逻辑沿用了踩过坑的经验：
  - EchoMusic 插件给的歌词行时间戳单位是**秒**（`currentTime` 也是秒，
    只有 `updatedAt` 是毫秒），这里做单位自动识别
  - 用插件给的 `currentIndex` 做交叉校验，偏差过大时以后者为准
"""

import bisect
import json
import threading
import time
import unicodedata
from urllib import error as urlerror
from urllib import request as urlrequest

from . import hid as halohid
from .hid import MAX_TEXT_BYTES


# --------------------------------------------------------------------------
# 文本排版
# --------------------------------------------------------------------------

def display_width(text: str) -> int:
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def split_pages(text: str, max_columns: int):
    if max_columns <= 0 or display_width(text) <= max_columns:
        return [text]
    pages, current, width = [], "", 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + w > max_columns and current:
            pages.append(current)
            current, width = ch, w
        else:
            current += ch
            width += w
    if current:
        pages.append(current)
    return pages


def cut_to_columns(text: str, max_columns: int) -> str:
    if max_columns <= 0:
        return text
    out, width = "", 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + w > max_columns:
            break
        out += ch
        width += w
    return out


# --------------------------------------------------------------------------
# 时间轴
# --------------------------------------------------------------------------

def line_starts_ms(state: dict, lines, unit: str = "auto"):
    """把歌词行起始时间统一换算成毫秒（自动识别秒/毫秒）。"""
    raw = [float(ln.get("s") or 0) for ln in lines]
    if not raw:
        return []
    if unit == "seconds":
        return [v * 1000.0 for v in raw]
    if unit == "milliseconds":
        return raw
    top = max(raw)
    if top <= 0:
        return raw
    duration = float(state.get("duration") or 0)
    if duration > 0:
        return raw if top > duration * 10 else [v * 1000.0 for v in raw]
    return raw if top > 7200 else [v * 1000.0 for v in raw]


def estimated_position_ms(state: dict, now: float) -> float:
    base = max(0.0, float(state.get("currentTime") or 0)) * 1000.0
    offset = float(state.get("lyricOffset") or 0)
    if not state.get("isPlaying"):
        return base + offset
    updated = float(state.get("updatedAt") or (now * 1000))
    rate = max(0.1, float(state.get("playbackRate") or 1))
    pos = base + max(0.0, now * 1000.0 - updated) * rate
    duration = float(state.get("duration") or 0) * 1000.0
    if duration > 0:
        pos = min(pos, duration)
    return pos + offset


def current_line_index(state: dict, pos_ms: float, unit: str = "auto") -> int:
    lines = state.get("lines") or []
    if not lines:
        return -1
    report = state.get("currentIndex", -1)
    report_ok = isinstance(report, int) and 0 <= report < len(lines)
    starts = line_starts_ms(state, lines, unit)
    if not any(s > 0 for s in starts):
        return report if report_ok else -1
    idx = bisect.bisect_right(starts, pos_ms) - 1
    idx = max(0, min(idx, len(lines) - 1))
    if report_ok and abs(idx - report) > 5:
        return report
    return idx


# --------------------------------------------------------------------------
# 数据源
# --------------------------------------------------------------------------

class LyricSource:
    """EchoMusic 插件在本机暴露的 /state 接口。"""

    def __init__(self, cfg: dict, logger):
        self._cfg = cfg
        self._log = logger
        self._opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        self.last_error = ""
        self.online = False
        self._was_online = False
        self.last_ok_at = 0.0

    def set_cfg(self, cfg):
        self._cfg = cfg

    @property
    def url(self):
        return "http://%s:%d/state" % (self._cfg["host"], self._cfg["port"])

    def fetch(self):
        try:
            timeout = max(0.1, self._cfg["timeout_ms"] / 1000.0)
            with self._opener.open(self.url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.last_error = ""
            self.online = True
            self.last_ok_at = time.time()
            if not self._was_online:
                self._was_online = True
                self._log.info("已连接 EchoMusic 歌词桥（%s）" % self.url)
            return data
        except (urlerror.URLError, OSError, ValueError) as exc:
            self.last_error = str(exc)
            if self._was_online:
                self._was_online = False
                self._log.warn("EchoMusic 歌词桥断开了：%s" % exc)
            self.online = False
            return None


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------

class LyricEngine:
    POLL_MIN = 0.03

    def __init__(self, cfg: dict, logger, devices):
        self._cfg = cfg
        self._log = logger
        self._devices = devices
        self._source = LyricSource(cfg["source"], logger)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()

        self.enabled = bool(cfg["display"].get("enabled", True))

        # 渲染状态（跨轮次保留）
        self._last_sent = None
        self._last_sent_at = 0.0
        self._current_layout = None
        self._track_key = None
        self._track_started_at = 0.0
        self._in_idle_ui = False
        self._pages = []
        self._pages_key = None
        self._pages_started_at = 0.0
        self._lines_key = None
        self._lines_len = -1
        self._warned_key = None

        self._snapshot = {
            "source_online": False,
            "source_error": "",
            "enabled": self.enabled,
            "title": "",
            "artist": "",
            "album": "",
            "isPlaying": False,
            "currentTime": 0.0,
            "duration": 0.0,
            "lineIndex": -1,
            "lineCount": 0,
            "lineText": "",
            "sentText": "",
            "layout": "",
            "updatedAt": 0.0,
        }

    # -- 对外接口 ---------------------------------------------------------
    def set_cfg(self, cfg: dict):
        self._cfg = cfg
        self._source.set_cfg(cfg["source"])
        self.enabled = bool(cfg["display"].get("enabled", True))

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self._snapshot)
        snap["source_online"] = self._source.online
        snap["source_error"] = self._source.last_error
        snap["enabled"] = self.enabled
        return snap

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lyric-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def apply_style(self):
        """把当前布局重新下发一次（切歌或恢复显示时用）。"""
        self._current_layout = None
        self._send_layout(self._base_layout())

    def restore_on_exit(self):
        display = self._cfg["display"]
        if self._in_idle_ui and display.get("restore_ui_mode_on_exit", True):
            dev = self._devices.device()
            if dev:
                dev.set_ui_mode(display.get("ui_mode", "clock"), tuple(display["color"]))

    # -- 布局 -------------------------------------------------------------
    def _scroll_layout(self):
        direction = str(self._cfg["display"].get("scroll_direction", "right_to_left")).lower()
        return "scroll_left_to_right" if direction in ("left_to_right", "l2r") else "scroll_right_to_left"

    def _base_layout(self):
        return self._scroll_layout() if self._cfg["display"].get("scroll_always", True) \
            else self._cfg["display"]["layout"]

    def _send_layout(self, name):
        if not name or name == self._current_layout:
            return False
        dev = self._devices.device()
        if dev is None:
            return False
        if dev.set_layout(name, tuple(self._cfg["display"]["color"])):
            self._current_layout = name
            self._log.info("布局切换 → %s" % halohid.LAYOUT_LABELS.get(name, name))
            return True
        return False

    # -- 发送 -------------------------------------------------------------
    def _send_text(self, text, layout=None):
        if text is None:
            return
        layout_changed = self._send_layout(layout) if layout else False
        if not layout_changed and text == self._last_sent:
            return
        dev = self._devices.device()
        if dev is None:
            return
        if dev.show_text(text):
            self._last_sent = text
            self._last_sent_at = time.time()
            with self._lock:
                self._snapshot["sentText"] = text
                self._snapshot["layout"] = layout or self._current_layout or ""
            self._log.info("屏幕 ← 「%s」" % text)
        else:
            self._log.warn("写入设备失败：%r" % text)

    def _emit(self, text, now):
        """长句策略：全局滚动 / 分页 / 截断，并处理单包字节上限。"""
        if text is None:
            return
        display = self._cfg["display"]
        cols = int(display["max_columns"])
        base_layout = display.get("layout", "center")
        mode = str(display.get("long_line_mode", "scroll")).lower()
        too_long = display_width(text) > cols

        want_scroll = display.get("scroll_always", True) or (too_long and mode == "scroll")

        if want_scroll:
            n_bytes = len(text.encode("utf-8"))
            if n_bytes <= MAX_TEXT_BYTES:
                repeat = float(display.get("scroll_repeat_seconds", 0) or 0)
                if repeat > 0 and text == self._last_sent and (now - self._last_sent_at) >= repeat:
                    self._last_sent = None
                self._send_text(text, layout=self._scroll_layout())
                return
            if n_bytes > MAX_TEXT_BYTES:
                if self._warned_key != text:
                    self._warned_key = text
                    self._log.warn("单句 %d 字节超出单包上限(%d)，改用分页：%s"
                                   % (n_bytes, MAX_TEXT_BYTES, text[:24]))
                self._page(text, now, base_layout)
                return

        if not too_long:
            self._send_text(text, layout=base_layout)
            return

        if mode == "cut":
            self._send_text(cut_to_columns(text, cols), layout=base_layout)
            return

        self._page(text, now, base_layout)

    def _page(self, text, now, layout):
        cols = int(self._cfg["display"]["max_columns"])
        if text != self._pages_key:
            self._pages_key = text
            self._pages = split_pages(text, cols)
            self._pages_started_at = now
        if not self._pages:
            return
        step = max(0.4, float(self._cfg["display"].get("scroll_seconds", 1.6)))
        page = int((now - self._pages_started_at) / step) % len(self._pages)
        self._send_text(self._pages[page], layout=layout)

    # -- 主循环 -----------------------------------------------------------
    def _loop(self):
        while not self._stop.is_set():
            started = time.time()
            try:
                if not self.enabled:
                    self._stop.wait(0.4)
                    continue
                interval = max(self.POLL_MIN, float(self._cfg["source"].get("poll_interval_ms", 120)) / 1000.0)
                state = self._source.fetch()
                if state is not None:
                    self._tick(state, started)
                else:
                    self._idle(started, "\u2014")
                spent = time.time() - started
                self._stop.wait(max(0.0, interval - spent))
            except Exception as exc:  # noqa: BLE001
                self._log.error("歌词引擎异常：%s" % exc)
                self._stop.wait(1.0)

    def _tick(self, state, now):
        display = self._cfg["display"]
        unit = self._cfg["source"].get("time_unit", "auto")
        lines = state.get("lines") or []
        title = (state.get("title") or "").strip()
        artist = (state.get("artist") or "").strip()

        track_key = title + "\u0001" + artist
        if track_key != self._track_key:
            self._track_key = track_key
            self._track_started_at = now
            self._last_sent = None
            self._pages_key = None
            if title:
                self._log.info("正在播放：%s - %s" % (title, artist))

        with self._lock:
            self._snapshot.update({
                "title": title,
                "artist": artist,
                "album": state.get("album") or "",
                "isPlaying": bool(state.get("isPlaying")),
                "currentTime": float(state.get("currentTime") or 0),
                "duration": float(state.get("duration") or 0),
                "lineCount": len(lines),
                "updatedAt": now,
            })
            # 歌词全量只在换歌 / 行数变化时重建，避免每轮都造垃圾
            if self._lines_key != track_key or self._lines_len != len(lines):
                self._lines_key = track_key
                self._lines_len = len(lines)
                self._snapshot["trackKey"] = track_key
                self._snapshot["lines"] = [
                    {"t": (ln.get("t") or ""), "s": float(ln.get("s") or 0)} for ln in lines
                ]

        if not title:
            self._idle(now, "\u2014")
            return

        remain = float(display.get("song_info_seconds", 3.0)) - (now - self._track_started_at)
        if display.get("song_info_seconds", 3.0) > 0 and remain > 0:
            info = title if not artist else "%s - %s" % (title, artist)
            self._leave_idle()
            self._set_line(-1, info)
            self._emit(info, now)
            return

        if not lines:
            note = "..." if state.get("lyricLoading") else "\u2014"
            self._idle(now, note)
            return

        pos = estimated_position_ms(state, now) + float(display.get("lyric_offset_ms", 0) or 0)
        idx = current_line_index(state, pos, unit)
        if idx < 0:
            self._idle(now, display.get("placeholder", "\u266a"))
            return

        entry = lines[idx]
        text = (entry.get("t") or "").strip()
        if display.get("show_translation") and (entry.get("r") or "").strip():
            text = "%s %s" % (text, entry["r"].strip())
        if not text:
            text = display.get("placeholder", "\u266a")
        if display.get("show_progress"):
            text = "%s[%d/%d]" % (text, idx + 1, len(lines))

        self._leave_idle()
        self._set_line(idx, text)
        self._emit(text, now)

    def _set_line(self, idx, text):
        with self._lock:
            self._snapshot["lineIndex"] = idx
            self._snapshot["lineText"] = text

    def _idle(self, now, note):
        """没有歌曲/歌词时：显示占位符，超时切到 UI 模式。"""
        display = self._cfg["display"]
        self._set_line(-1, note)
        self._emit(note, now)
        idle_after = float(display.get("idle_to_ui_seconds", 30.0))
        if idle_after > 0 and (now - self._track_started_at) > idle_after and not self._in_idle_ui:
            dev = self._devices.device()
            if dev is None:
                return
            ui_mode = display.get("ui_mode", "clock")
            if dev.set_ui_mode(ui_mode, tuple(display["color"])):
                self._log.info("待机 → 切换到 UI 模式：%s"
                               % halohid.UI_MODE_LABELS.get(ui_mode, ui_mode))
                self._in_idle_ui = True

    def _leave_idle(self):
        if self._in_idle_ui:
            self._log.info("恢复文字显示")
            self._current_layout = None
            self._send_layout(self._base_layout())
            self._in_idle_ui = False
