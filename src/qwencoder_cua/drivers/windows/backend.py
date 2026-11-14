from __future__ import annotations

import os
import subprocess
import time
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
        self._kernel32 = ctypes.windll.kernel32
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

    def capture_window(
        self, window_id: str, output: str | Path | None = None
    ):
        """Capture the selected window's client area, excluding title bars and borders."""
        self._check()
        hwnd = int(window_id)
        if not self._win32gui.IsWindow(hwnd):
            raise UnsupportedOperationError(f"Target window handle {window_id!r} is no longer valid.")
        if not self._win32gui.IsWindowVisible(hwnd):
            raise UnsupportedOperationError(f"Target window {window_id!r} is not visible.")
        try:
            import mss
            from PIL import Image

            left, top, right, bottom = self._win32gui.GetClientRect(hwnd)
            width, height = right - left, bottom - top
            screen_left, screen_top = self._win32gui.ClientToScreen(hwnd, (0, 0))
            if width <= 0 or height <= 0:
                raise UnsupportedOperationError("Target window has an empty client area.")
            region = {
                "left": int(screen_left),
                "top": int(screen_top),
                "width": int(width),
                "height": int(height),
            }
            with mss.mss() as sct:
                shot = sct.grab(region)
                image = Image.frombytes("RGB", shot.size, shot.rgb)
            if output:
                image.save(output)
            return image, (
                int(screen_left), int(screen_top), int(width), int(height)
            )
        except UnsupportedOperationError:
            raise
        except Exception as exc:
            raise DriverUnavailableError(
                f"Could not capture target window {window_id!r}: {exc}"
            ) from exc

    def _window_info(self, hwnd: int, active: bool = False) -> WindowInfo:
        title = self._win32gui.GetWindowText(hwnd)
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
        return WindowInfo(
            id=str(hwnd),
            title=title,
            process_id=pid,
            process_name=process_name,
            visible=bool(self._win32gui.IsWindowVisible(hwnd)),
            minimized=bool(self._win32gui.IsIconic(hwnd)),
            bounds=bounds,
            is_active=active,
        )

    def get_windows(self):
        self._check()
        result = []

        def callback(hwnd, _):
            if not self._win32gui.IsWindowVisible(hwnd):
                return
            title = self._win32gui.GetWindowText(hwnd)
            if not title.strip():
                return
            result.append(
                self._window_info(
                    hwnd, active=hwnd == self._win32gui.GetForegroundWindow()
                )
            )

        self._win32gui.EnumWindows(callback, None)
        return result

    def get_active_window(self):
        self._check()
        hwnd = self._win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        return self._window_info(hwnd, active=True)

    def focus_window(self, window_id: str):
        self._check()
        hwnd = int(window_id)
        if not self._win32gui.IsWindow(hwnd):
            raise ValueError(f"Unknown window handle: {window_id}")
        self._win32gui.ShowWindow(hwnd, self._win32con.SW_RESTORE)

        target_thread, _ = self._win32process.GetWindowThreadProcessId(hwnd)
        current_thread = self._kernel32.GetCurrentThreadId()
        attached = False
        try:
            if target_thread != current_thread:
                attached = bool(
                    self._user32.AttachThreadInput(current_thread, target_thread, True)
                )
            self._win32gui.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)
            self._user32.SetFocus(hwnd)
        finally:
            if attached:
                self._user32.AttachThreadInput(current_thread, target_thread, False)

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self._win32gui.GetForegroundWindow() == hwnd:
                return
            time.sleep(0.025)
        raise UnsupportedOperationError(
            "Windows did not allow QWENCODER to focus the selected application window. "
            "Click that application once, then rerun the task."
        )

    def click(self, x: int, y: int, button="left"):
        self._check()
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"Unsupported mouse button: {button}")
        self._pyautogui.click(x=x, y=y, button=button)

    def move(self, x: int, y: int):
        self._check()
        self._pyautogui.moveTo(x, y)

    def mouse_down(self, x: int, y: int, button="left"):
        self._check()
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"Unsupported mouse button: {button}")
        self._pyautogui.moveTo(x, y)
        self._pyautogui.mouseDown(button=button)

    def mouse_up(self, button="left"):
        self._check()
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"Unsupported mouse button: {button}")
        self._pyautogui.mouseUp(button=button)

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
