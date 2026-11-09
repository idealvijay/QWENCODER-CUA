from __future__ import annotations

import os
from pathlib import Path

from qwencoder_cua.core.driver import BaseDriver
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


class X11Driver(BaseDriver):
    name = "linux-x11"

    def __init__(self):
        self._connected = False
        self._display = None
        self._root = None
        self._xtest = None

    @property
    def capabilities(self):
        return DriverCapabilities(
            screenshot=True, window_enumeration=True, window_focus=True,
            mouse_input=True, keyboard_input=True, global_input=True,
            background_input=False, accessibility=False, multi_monitor=False
        )

    def connect(self):
        if not os.environ.get("DISPLAY"):
            raise DriverUnavailableError("DISPLAY is not set.")
        try:
            from Xlib import X, display
            from Xlib.ext import xtest
            self._X = X
            self._display = display.Display()
            self._root = self._display.screen().root
            self._xtest = xtest
            self._connected = True
        except Exception as exc:
            raise DriverUnavailableError(
                "Unable to connect to X11. Install python-xlib and ensure X access is permitted."
            ) from exc

    def disconnect(self):
        if self._display:
            self._display.close()
        self._display = self._root = None
        self._connected = False

    def _check(self):
        if not self._connected:
            raise RuntimeError("X11 driver is not connected.")

    def screenshot(self, output: str | Path | None = None):
        self._check()
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                image = Image.frombytes("RGB", shot.size, shot.rgb)
            if output:
                image.save(output)
            return image
        except Exception as exc:
            raise DriverUnavailableError(f"X11 screenshot failed: {exc}") from exc

    def get_windows(self):
        self._check()
        result = []
        try:
            tree = self._root.query_tree()
            for window in tree.children:
                try:
                    attrs = window.get_attributes()
                    if attrs.map_state == self._X.IsUnmapped:
                        continue
                    title = window.get_wm_name() or ""
                    if not title:
                        continue
                    geom = window.get_geometry()
                    result.append(WindowInfo(
                        id=str(window.id), title=title,
                        bounds=(geom.x, geom.y, geom.width, geom.height),
                        visible=True
                    ))
                except Exception:
                    continue
        except Exception as exc:
            raise DriverUnavailableError(f"X11 window enumeration failed: {exc}") from exc
        return result

    def get_active_window(self):
        self._check()
        try:
            atom = self._display.intern_atom("_NET_ACTIVE_WINDOW")
            prop = self._root.get_full_property(atom, self._X.AnyPropertyType)
            if not prop or not len(prop.value):
                return None
            wid = int(prop.value[0])
            for win in self.get_windows():
                if win.id == str(wid):
                    win.is_active = True
                    return win
            return WindowInfo(id=str(wid), is_active=True)
        except Exception:
            return None

    def focus_window(self, window_id: str):
        self._check()
        wid = int(window_id)
        window = self._display.create_resource_object("window", wid)
        window.set_input_focus(self._X.RevertToParent, self._X.CurrentTime)
        self._display.flush()

    def _fake(self, event_type, detail):
        self._xtest.fake_input(self._display, event_type, detail)
        self._display.sync()

    def click(self, x: int, y: int, button="left"):
        self._check()
        from Xlib import X
        buttons = {"left": 1, "middle": 2, "right": 3}
        if button not in buttons:
            raise ValueError(f"Unsupported mouse button: {button}")
        self.move(x, y)
        self._fake(X.ButtonPress, buttons[button])
        self._fake(X.ButtonRelease, buttons[button])

    def move(self, x: int, y: int):
        self._check()
        from Xlib import X
        self._xtest.fake_input(self._display, X.MotionNotify, x=x, y=y)
        self._display.sync()

    def scroll(self, dx=0, dy=0):
        self._check()
        from Xlib import X
        for button, count in ((6 if dx < 0 else 7, abs(dx)), (4 if dy > 0 else 5, abs(dy))):
            for _ in range(count):
                self._fake(X.ButtonPress, button)
                self._fake(X.ButtonRelease, button)

    def type_text(self, text: str):
        self._check()
        raise UnsupportedOperationError(
            "X11 text typing requires an optional XTest/keyboard mapping adapter; "
            "use press_key for mapped keys in this initial build."
        )

    def press_key(self, key: str):
        self._check()
        from Xlib import X
        from Xlib import XK
        keysym = XK.string_to_keysym(key)
        if not keysym:
            raise ValueError(f"Unknown X11 keysym: {key}")
        keycode = self._display.keysym_to_keycode(keysym)
        if not keycode:
            raise ValueError(f"No keycode mapped for keysym: {key}")
        self._fake(X.KeyPress, keycode)
        self._fake(X.KeyRelease, keycode)
