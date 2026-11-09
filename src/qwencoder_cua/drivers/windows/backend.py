from __future__ import annotations

import os
import subprocess
from pathlib import Path

from qwencoder_cua.core.driver import BaseDriver
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


class WindowsDriver(BaseDriver):
    name = "windows"

    def __init__(self):
        self._connected = False
        self._user32 = None
        self._pyautogui = None

    @property
    def capabilities(self):
        return DriverCapabilities(
            screenshot=True, window_enumeration=True, window_focus=True,
            mouse_input=True, keyboard_input=True, clipboard=False,
            global_input=True, background_input=False,
        )

    def connect(self):
        if os.name != "nt":
            raise DriverUnavailableError("WindowsDriver can only run on Windows.")
        try:
            import win32gui
            import win32con
            import win32process
            import win32api
            import pyautogui
        except ImportError as exc:
            raise DriverUnavailableError(
                'Install Windows extras: pip install -e ".[windows]"'
            ) from exc
        import ctypes
        self._win32gui = win32gui
        self._win32con = win32con
        self._win32process = win32process
        self._win32api = win32api
        self._pyautogui = pyautogui
        self._user32 = ctypes.windll.user32
        self._connected = True

    def disconnect(self):
        self._connected = False

    def _check(self):
        if not self._connected:
            raise RuntimeError("Windows driver is not connected.")

    def screenshot(self, output: str | Path | None = None):
        self._check()
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                image = Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as exc:
            raise DriverUnavailableError(f"Screenshot capture failed: {exc}") from exc
        if output:
            image.save(output)
        return image

    def get_windows(self):
        self._check()
        result = []

        def callback(hwnd, _):
            if not self._win32gui.IsWindowVisible(hwnd):
                return
            title = self._win32gui.GetWindowText(hwnd)
            if not title.strip():
                return
            try:
                _, pid = self._win32process.GetWindowThreadProcessId(hwnd)
                import psutil
                process_name = psutil.Process(pid).name()
            except Exception:
                pid, process_name = None, None
            try:
                left, top, right, bottom = self._win32gui.GetWindowRect(hwnd)
                bounds = (left, top, right - left, bottom - top)
            except Exception:
                bounds = None
            result.append(WindowInfo(
                id=str(hwnd), title=title, process_id=pid,
                process_name=process_name, bounds=bounds,
                is_active=hwnd == self._win32gui.GetForegroundWindow(),
            ))

        self._win32gui.EnumWindows(callback, None)
        return result

    def get_active_window(self):
        self._check()
        hwnd = self._win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = self._win32gui.GetWindowText(hwnd)
        try:
            _, pid = self._win32process.GetWindowThreadProcessId(hwnd)
            import psutil
            pname = psutil.Process(pid).name()
        except Exception:
            pid, pname = None, None
        try:
            l, t, r, b = self._win32gui.GetWindowRect(hwnd)
            bounds = (l, t, r-l, b-t)
        except Exception:
            bounds = None
        return WindowInfo(
            id=str(hwnd), title=title, process_id=pid,
            process_name=pname, bounds=bounds, is_active=True
        )

    def focus_window(self, window_id: str):
        self._check()
        hwnd = int(window_id)
        if not self._win32gui.IsWindow(hwnd):
            raise ValueError(f"Unknown window handle: {window_id}")
        self._win32gui.ShowWindow(hwnd, self._win32con.SW_RESTORE)
        self._win32gui.SetForegroundWindow(hwnd)

    def click(self, x: int, y: int, button="left"):
        self._check()
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"Unsupported mouse button: {button}")
        self._pyautogui.click(x=x, y=y, button=button)

    def move(self, x: int, y: int):
        self._check()
        self._pyautogui.moveTo(x, y)

    def scroll(self, dx=0, dy=0):
        self._check()
        if dx:
            self._pyautogui.hscroll(dx)
        if dy:
            self._pyautogui.scroll(dy)

    def type_text(self, text: str):
        self._check()
        self._pyautogui.write(text, interval=0.01)

    def press_key(self, key: str):
        self._check()
        self._pyautogui.press(key)

    def launch_application(self, command: str, args=None):
        self._check()
        completed = subprocess.Popen([command, *(args or [])])
        return completed.pid
