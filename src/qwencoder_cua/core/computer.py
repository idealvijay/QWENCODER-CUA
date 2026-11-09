from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from qwencoder_cua.core.registry import create_driver
from qwencoder_cua.models.observation import Observation, ScreenshotRef


class Computer:
    """Simple synchronous facade over the selected local platform driver."""

    def __init__(self, driver=None):
        self.driver = driver or create_driver()
        self.session_id = str(uuid4())
        self._connected = False
        self._last_observation_id: str | None = None

    def connect(self):
        if not self._connected:
            self.driver.connect()
            self._connected = True
        return self

    def disconnect(self):
        if self._connected:
            self.driver.disconnect()
            self._connected = False

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()

    def screenshot(self, output: str | Path | None = None):
        self._require_connected()
        return self.driver.screenshot(output)

    def observe(self, screenshot_path: str | Path | None = None) -> Observation:
        self._require_connected()
        image = self.driver.screenshot(screenshot_path)
        active = self.driver.get_active_window()
        windows = self.driver.get_windows()
        width, height = image.size
        self._last_observation_id = str(uuid4())
        screenshot_ref = ScreenshotRef(
            path=str(screenshot_path) if screenshot_path else None,
            width=width,
            height=height,
        )
        return Observation(
            observation_id=self._last_observation_id,
            platform=self.driver.name,
            session_type=getattr(self.driver, "session_type", None),
            active_window=active,
            windows=windows,
            screenshot=screenshot_ref,
        )

    def windows(self):
        self._require_connected()
        return self.driver.get_windows()

    def active_window(self):
        self._require_connected()
        return self.driver.get_active_window()

    def focus_window(self, window_id: str):
        self._require_connected()
        return self.driver.focus_window(window_id)

    def click(self, x: int, y: int, button: str = "left"):
        self._require_connected()
        return self.driver.click(x, y, button)

    def move(self, x: int, y: int):
        self._require_connected()
        return self.driver.move(x, y)

    def scroll(self, dx: int = 0, dy: int = 0):
        self._require_connected()
        return self.driver.scroll(dx, dy)

    def type_text(self, text: str):
        self._require_connected()
        return self.driver.type_text(text)

    def press_key(self, key: str):
        self._require_connected()
        return self.driver.press_key(key)

    def _require_connected(self):
        if not self._connected:
            raise RuntimeError("Computer is not connected. Use connect() or a context manager.")
