from __future__ import annotations

import platform

from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.core.registry import detect_linux_session
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.drivers.linux.x11.backend import X11Driver
from qwencoder_cua.core.driver import BaseDriver


class LinuxDriver(BaseDriver):
    name = "linux"

    def __init__(self, session_type: str | None = None):
        self.session_type = session_type or detect_linux_session()
        self._backend = None

    @property
    def capabilities(self) -> DriverCapabilities:
        if self._backend:
            return self._backend.capabilities
        if self.session_type == "wayland":
            return DriverCapabilities(screenshot=False, global_input=False)
        return DriverCapabilities()

    def connect(self):
        if platform.system() != "Linux":
            raise DriverUnavailableError("LinuxDriver can only run on Linux.")
        if self.session_type == "x11":
            self._backend = X11Driver()
            self._backend.connect()
            return
        if self.session_type == "wayland":
            from qwencoder_cua.drivers.linux.wayland.backend import WaylandPortalDriver
            self._backend = WaylandPortalDriver()
            self._backend.connect()
            return
        raise DriverUnavailableError(
            "No supported graphical session detected. Check DISPLAY or WAYLAND_DISPLAY "
            "and XDG_SESSION_TYPE."
        )

    def disconnect(self):
        if self._backend:
            self._backend.disconnect()
            self._backend = None

    def _delegate(self, method, *args, **kwargs):
        if not self._backend:
            raise RuntimeError("Linux driver is not connected.")
        return getattr(self._backend, method)(*args, **kwargs)

    def screenshot(self, output=None):
        return self._delegate("screenshot", output)

    def get_windows(self):
        return self._delegate("get_windows")

    def get_active_window(self):
        return self._delegate("get_active_window")

    def focus_window(self, window_id):
        return self._delegate("focus_window", window_id)

    def click(self, x, y, button="left"):
        return self._delegate("click", x, y, button)

    def move(self, x, y):
        return self._delegate("move", x, y)

    def scroll(self, dx=0, dy=0):
        return self._delegate("scroll", dx, dy)

    def type_text(self, text):
        return self._delegate("type_text", text)

    def press_key(self, key):
        return self._delegate("press_key", key)
