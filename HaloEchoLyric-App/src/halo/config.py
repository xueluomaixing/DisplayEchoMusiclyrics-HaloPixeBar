# -*- coding: utf-8 -*-
"""配置与日志路径管理。

配置和日志都放在 %APPDATA%\\HaloEchoLyric 下，卸载脚本会一并清理。
"""

import json
import os
import sys
import threading
from datetime import datetime

APP_NAME = "HaloEchoLyric"

def _base_dir() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_NAME)
    return os.path.join(os.path.expanduser("~"), "." + APP_NAME)


BASE_DIR = _base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")


DEFAULT_CONFIG = {
    "device": {
        "auto_connect": True,
        "reconnect_interval_ms": 3000,
    },
    "source": {
        "host": "127.0.0.1",
        "port": 38333,
        "timeout_ms": 400,
        "poll_interval_ms": 120,
        "time_unit": "auto",
    },
    "display": {
        "enabled": True,
        "scroll_always": True,
        "long_line_mode": "scroll",     # scroll / paging / cut
        "scroll_direction": "right_to_left",
        "scroll_repeat_seconds": 0.0,
        "scroll_seconds": 1.6,
        "layout": "center",
        "ui_mode": "clock",
        "max_columns": 20,
        "color": [255, 255, 255],
        "show_progress": False,
        "show_translation": False,
        "song_info_seconds": 3.0,
        "lyric_offset_ms": 0,
        "idle_to_ui_seconds": 30.0,
        "restore_ui_mode_on_exit": True,
        "placeholder": "\u266a",
    },
    "light": {
        "enabled": False,
        "effect": "dynamic",
        "color": [255, 255, 255],
        "brightness": "high",
        "speed": 10,
    },
    "ui": {
        "close_action": "tray",         # tray / exit
        "autostart": False,
        "minimize_on_autostart": True,
    },
    "window": {
        "width": 1120,
        "height": 720,
    },
}

_lock = threading.RLock()


def deep_merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def load() -> dict:
    with _lock:
        ensure_dirs()
        if not os.path.exists(CONFIG_PATH):
            save(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                user = json.load(fh)
        except Exception:
            save(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        return deep_merge(DEFAULT_CONFIG, user)


def save(cfg: dict) -> bool:
    with _lock:
        try:
            ensure_dirs()
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
            return True
        except Exception:
            return False


class Logger:
    """同时写文件与内存缓冲，供界面「日志」页展示。"""

    MAX_LINES = 500

    def __init__(self):
        self._lines = []
        self._lock = threading.RLock()
        self._path = None
        try:
            ensure_dirs()
            self._path = os.path.join(LOG_DIR, "app-%s.log" % datetime.now().strftime("%Y-%m-%d"))
        except Exception:
            self._path = None

    def log(self, level: str, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = "%s  %-5s %s" % (stamp, level.upper(), message)
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self.MAX_LINES:
                del self._lines[: len(self._lines) - self.MAX_LINES]
            if self._path:
                try:
                    with open(self._path, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except Exception:
                    pass
        return line

    def info(self, message):
        return self.log("INFO", message)

    def warn(self, message):
        return self.log("WARN", message)

    def error(self, message):
        return self.log("ERROR", message)

    def lines(self):
        with self._lock:
            return list(self._lines)

    def clear(self):
        with self._lock:
            self._lines.clear()

    @property
    def path(self):
        return self._path


LOG = Logger()
