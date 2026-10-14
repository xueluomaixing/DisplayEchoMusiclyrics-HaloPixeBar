# -*- coding: utf-8 -*-
"""HaloEchoLyric —— EchoMusic 歌词同步花再 Halo PixelBar 控制中心。

GUI：pywebview + WebView2（必须显式指定 edgechromium，否则会静默退化成 IE 内核）。
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from halo import APP_TITLE, __version__          # noqa: E402
from halo import config as cfgmod                # noqa: E402
from halo import hid as halohid                  # noqa: E402
from halo.device import DeviceManager            # noqa: E402
from halo.engine import LyricEngine              # noqa: E402

import webview                                   # noqa: E402


PLUGIN_ID = "halo-pixelbar-lyric"
ECHOMUSIC_PLUGIN_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "echo-music", "plugins")


def resource_path(*parts) -> str:
    """兼容开发运行与 PyInstaller 打包后的资源定位。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


_MUTEX_HANDLE = None


def acquire_single_instance() -> bool:
    """命名互斥体保证同时只有一个实例。

    两个实例会抢同一个 HID 设备、互相覆盖屏幕内容，所以必须挡住。
    """
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, "Local\\HaloEchoLyricApp")
        if not handle:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:  # noqa: BLE001
        return True


def focus_existing_window() -> bool:
    """已经有一个实例时，把它从托盘/最小化状态唤到前台。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)         # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False



def hex_to_rgb(value, fallback=(255, 255, 255)):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return tuple(int(v) & 0xFF for v in value[:3])
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return fallback
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return fallback


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % (rgb[0], rgb[1], rgb[2])


class Api:
    """暴露给前端 JS 的接口。所有方法必须可 JSON 序列化返回值。"""

    def __init__(self):
        self.cfg = cfgmod.load()
        self.log = cfgmod.LOG
        self.devices = DeviceManager(self.cfg, self.log)
        self.engine = LyricEngine(self.cfg, self.log, self.devices)
        self.window = None
        self._tray = None
        self._quitting = False
        self.log.info("%s v%s 启动" % (APP_TITLE, __version__))

    # -- 生命周期 ---------------------------------------------------------
    def bind_window(self, window):
        self.window = window
        self.devices.start_watch(lambda _s: None)
        self.engine.start()
        if self.cfg["device"].get("auto_connect", True):
            threading.Thread(target=self.devices.connect, daemon=True).start()

    def shutdown(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            self.engine.restore_on_exit()
        except Exception:
            pass
        self.engine.stop()
        self.devices.stop()
        self.devices.disconnect("程序退出")
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.log.info("程序退出")

    # -- 状态 -------------------------------------------------------------
    def get_state(self):
        return {
            "ok": True,
            "app": {"title": APP_TITLE, "version": __version__},
            "device": self.devices.status(),
            "lyric": self.engine.snapshot(),
            "config": self.cfg,
            "plugin": self.plugin_status(),
            "logs": self.log.lines(),
            "options": {
                "layouts": halohid.LAYOUT_LABELS,
                "uiModes": halohid.UI_MODE_LABELS,
                "lightEffects": halohid.LIGHT_EFFECT_LABELS,
                "lightBrightness": halohid.LIGHT_BRIGHTNESS_LABELS,
                "maxTextBytes": halohid.MAX_TEXT_BYTES,
            },
        }

    # -- 设备 -------------------------------------------------------------
    def scan_devices(self):
        items = self.devices.scan()
        return {"ok": True, "count": len(items),
                "items": [{"describe": it.describe(), "isScreen": it.is_screen,
                           "interface": it.interface, "usagePage": "0x%04X" % it.usage_page}
                          for it in items]}

    def connect_device(self):
        ok = self.devices.connect()
        return {"ok": ok, "device": self.devices.status()}

    def disconnect_device(self):
        self.devices.disconnect()
        return {"ok": True, "device": self.devices.status()}

    # -- 配置 -------------------------------------------------------------
    def set_config(self, patch):
        self.cfg = cfgmod.deep_merge(self.cfg, patch or {})
        cfgmod.save(self.cfg)
        self.devices.set_cfg(self.cfg)
        self.engine.set_cfg(self.cfg)
        return {"ok": True, "config": self.cfg}

    def reset_config(self):
        self.cfg = cfgmod.deep_merge(cfgmod.DEFAULT_CONFIG, {})
        cfgmod.save(self.cfg)
        self.devices.set_cfg(self.cfg)
        self.engine.set_cfg(self.cfg)
        self.log.info("配置已恢复默认")
        return {"ok": True, "config": self.cfg}

    # -- 屏幕 -------------------------------------------------------------
    def send_custom_text(self, text):
        dev = self.devices.device()
        if dev is None:
            return {"ok": False, "error": "设备未连接"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "文字为空"}
        ok = dev.show_text(text)
        self.log.info("发送自定义文字：「%s」%s" % (text, "成功" if ok else "失败"))
        return {"ok": ok}

    def set_screen_color(self, color):
        dev = self.devices.device()
        if dev is None:
            return {"ok": False, "error": "设备未连接"}
        rgb = hex_to_rgb(color)
        ok = dev.set_screen_color(rgb)
        self.log.info("屏幕纯色：%s %s" % (rgb_to_hex(rgb), "成功" if ok else "失败"))
        return {"ok": ok}

    def set_ui_mode(self, mode):
        dev = self.devices.device()
        if dev is None:
            return {"ok": False, "error": "设备未连接"}
        ok = dev.set_ui_mode(mode, tuple(self.cfg["display"]["color"]))
        self.log.info("UI 模式：%s %s" % (halohid.UI_MODE_LABELS.get(mode, mode),
                                       "成功" if ok else "失败"))
        return {"ok": ok}

    def send_test_text(self):
        """快速自检：往屏幕发一行测试文字。"""
        dev = self.devices.device()
        if dev is None:
            return {"ok": False, "error": "设备未连接"}
        dev.set_layout("center", tuple(self.cfg["display"]["color"]))
        time.sleep(0.12)
        ok = dev.show_text("\u266a HALO ECHO TEST \u266a")
        return {"ok": ok}

    # -- 灯光 -------------------------------------------------------------
    def apply_light(self, effect, color, brightness, speed, enabled=True):
        dev = self.devices.device()
        if dev is None:
            return {"ok": False, "error": "设备未连接"}
        rgb = hex_to_rgb(color)
        if enabled:
            ok = dev.set_ambient_light(effect, rgb, brightness, int(speed))
        else:
            ok = dev.set_ambient_power(False)
        self.cfg["light"].update({"enabled": bool(enabled), "effect": effect,
                                  "color": list(rgb), "brightness": brightness,
                                  "speed": int(speed)})
        cfgmod.save(self.cfg)
        self.log.info("灯效：%s / %s / %s 速度%d %s"
                      % (halohid.LIGHT_EFFECT_LABELS.get(effect, effect),
                         rgb_to_hex(rgb), brightness, int(speed),
                         "成功" if ok else "失败"))
        return {"ok": ok}

    # -- 插件 -------------------------------------------------------------
    def plugin_status(self):
        target = os.path.join(ECHOMUSIC_PLUGIN_DIR, PLUGIN_ID)
        has_dir = os.path.isdir(os.path.join(ECHOMUSIC_PLUGIN_DIR))
        return {
            "echoMusicDir": ECHOMUSIC_PLUGIN_DIR,
            "echoMusicFound": has_dir,
            "installed": os.path.isfile(os.path.join(target, "manifest.json")),
            "path": target,
            "pluginFlow": False,
            "sourceOnline": self.engine.snapshot().get("source_online", False),
        }

    def install_plugin(self):
        src = resource_path("plugin")
        if not os.path.isdir(src):
            return {"ok": False, "error": "安装包内未找到插件文件"}
        if not os.path.isdir(ECHOMUSIC_PLUGIN_DIR):
            return {"ok": False, "error": "未找到 EchoMusic 插件目录，请先运行一次 EchoMusic"}
        dst = os.path.join(ECHOMUSIC_PLUGIN_DIR, PLUGIN_ID)
        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        except Exception as exc:  # noqa: BLE001
            self.log.error("插件安装失败：%s" % exc)
            return {"ok": False, "error": str(exc)}
        self.log.info("插件已安装到 %s（请在 EchoMusic 插件管理中启用）" % dst)
        return {"ok": True, "path": dst,
                "message": "已安装。请在 EchoMusic → 插件管理中启用「Halo PixelBar 歌词桥」"}

    def remove_plugin(self):
        dst = os.path.join(ECHOMUSIC_PLUGIN_DIR, PLUGIN_ID)
        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        self.log.info("插件已移除")
        return {"ok": True}

    # -- 系统 -------------------------------------------------------------
    def _startup_dir(self):
        return os.path.join(os.environ.get("APPDATA", ""),
                            "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

    def _shortcut_path(self):
        return os.path.join(self._startup_dir(), "HaloEchoLyric.lnk")

    def set_autostart(self, enabled):
        enabled = bool(enabled)
        path = self._shortcut_path()
        try:
            if enabled:
                target = sys.executable
                if not getattr(sys, "frozen", False):
                    return {"ok": False, "error": "开发模式下不支持设置开机自启"}
                ps = (
                    "$w=New-Object -ComObject WScript.Shell;"
                    "$s=$w.CreateShortcut('%s');"
                    "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
                    "$s.WindowStyle=7;$s.Description='HaloEchoLyric';$s.Save()"
                    % (path, target, os.path.dirname(target))
                )
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-Command", ps], capture_output=True, timeout=20)
                ok = os.path.isfile(path)
                self.cfg["ui"]["autostart"] = ok
            else:
                if os.path.isfile(path):
                    os.remove(path)
                ok = not os.path.isfile(path)
                self.cfg["ui"]["autostart"] = False
            cfgmod.save(self.cfg)
            self.log.info("开机自启：%s" % ("开启" if enabled and ok else "关闭"))
            return {"ok": ok}
        except Exception as exc:  # noqa: BLE001
            self.log.error("设置开机自启失败：%s" % exc)
            return {"ok": False, "error": str(exc)}

    def open_log_dir(self):
        try:
            cfgmod.ensure_dirs()
            os.startfile(cfgmod.LOG_DIR)  # noqa: S606
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def clear_logs(self):
        self.log.clear()
        return {"ok": True}

    def uninstall(self):
        """清理插件 / 自启 / 配置目录，然后删除自身。"""
        lines = ["@echo off", "ping -n 3 127.0.0.1 >nul"]
        lines.append('rmdir /s /q "%s"' % os.path.join(ECHOMUSIC_PLUGIN_DIR, PLUGIN_ID))
        lines.append('del /f /q "%s"' % self._shortcut_path())
        lines.append('rmdir /s /q "%s"' % cfgmod.BASE_DIR)
        exe_dir = os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False):
            lines.append('cd /d "%TEMP%"')
            lines.append('rmdir /s /q "%s"' % exe_dir)
        script = os.path.join(os.environ.get("TEMP", "."), "haloecho_uninstall.bat")
        try:
            with open(script, "w", encoding="mbcs" if os.name == "nt" else "utf-8") as fh:
                fh.write("\r\n".join(lines) + "\r\n")
            subprocess.Popen(["cmd", "/c", script], creationflags=0x08000000,
                             cwd=os.environ.get("TEMP", "."))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        self.log.info("已开始卸载清理，程序将退出")
        threading.Timer(0.8, self.quit_app).start()
        return {"ok": True}

    # -- 窗口 -------------------------------------------------------------
    def minimize(self):
        if self.window:
            self.window.minimize()
        return {"ok": True}

    def toggle_maximize(self):
        if not self.window:
            return {"ok": True, "maximized": False}
        try:
            if getattr(self.window, "maximized", False):
                self.window.restore()
            else:
                self.window.maximize()
            return {"ok": True, "maximized": bool(getattr(self.window, "maximized", False))}
        except Exception:
            return {"ok": True, "maximized": False}

    def quit_app(self):
        self.shutdown()
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        return {"ok": True}

    def request_close(self):
        """标题栏关闭按钮：按配置决定最小化还是退出。"""
        if self.cfg["ui"].get("close_action", "tray") == "tray":
            if self.window:
                self.window.hide()
            self._ensure_tray()
            return {"ok": True, "action": "hide"}
        self.quit_app()
        return {"ok": True, "action": "exit"}

    # -- 托盘 -------------------------------------------------------------
    def _ensure_tray(self):
        if self._tray:
            return
        try:
            import pystray
            from PIL import Image, ImageDraw

            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([6, 20, 58, 44], radius=8, fill=(83, 74, 183, 255))
            d.ellipse([16, 8, 26, 18], fill=(127, 119, 221, 255))
            d.ellipse([38, 8, 48, 18], fill=(127, 119, 221, 255))

            def show(icon, _item):
                if self.window:
                    self.window.show()
                    try:
                        self.window.restore()
                    except Exception:
                        pass

            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", show, default=True),
                pystray.MenuItem("退出", lambda icon, _i: (icon.stop(), self.quit_app())),
            )
            self._tray = pystray.Icon("HaloEchoLyric", img, "HaloEchoLyric", menu)
            self._tray.run_detached()
            self.log.info("已最小化到托盘")
        except Exception as exc:  # noqa: BLE001
            self.log.warn("托盘图标不可用（%s），改为最小化窗口" % exc)
            if self.window:
                self.window.show()
                self.window.minimize()


def main():
    # 单实例：已经有程序在跑就把它唤到前台，然后安静退出
    if not acquire_single_instance():
        focus_existing_window()
        return 0

    page = ""
    argv = sys.argv[1:]
    if "--page" in argv:
        try:
            page = argv[argv.index("--page") + 1]
        except IndexError:
            page = ""

    api = Api()
    url = resource_path("ui", "index.html")
    if page:
        url += "#" + page
    window = webview.create_window(
        APP_TITLE,
        url=url,
        js_api=api,
        width=int(api.cfg["window"].get("width", 1120)),
        height=int(api.cfg["window"].get("height", 720)),
        min_size=(960, 620),
        frameless=True,
        background_color="#0b1020",
        text_select=False,
    )
    api.bind_window(window)

    def on_closed():
        api.shutdown()

    try:
        window.events.closed += on_closed
    except Exception:
        pass

    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception:
        # WebView2 不可用时退回默认后端，至少还能起来
        webview.start(debug=False)
    api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
