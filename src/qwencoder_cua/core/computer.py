from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from qwencoder_cua.core.registry import create_driver
from qwencoder_cua.models.observation import Observation, ScreenshotRef
from qwencoder_cua.accessibility.tokens import ElementTokenStore
from qwencoder_cua.core.exceptions import UnsupportedOperationError

class Computer:
    """Synchronous local desktop facade with visual and accessibility observations."""
    def __init__(self, driver=None, accessibility=True, element_ttl=15.0):
        self.driver = driver or create_driver()
        self.session_id = str(uuid4())
        self._connected = False
        self._accessibility_enabled = accessibility
        self._provider = None
        self._tokens = ElementTokenStore(element_ttl)
        self._last_observation_id = None

    def connect(self):
        if not self._connected:
            self.driver.connect()
            self._connected = True
            if self._accessibility_enabled:
                try:
                    if self.driver.name == "windows":
                        from qwencoder_cua.drivers.windows.accessibility import WindowsUIAProvider
                        self._provider = WindowsUIAProvider()
                    elif self.driver.name == "linux":
                        from qwencoder_cua.drivers.linux.accessibility import LinuxATSPIProvider
                        self._provider = LinuxATSPIProvider()
                    if self._provider:
                        self._provider.connect()
                except Exception:
                    # Visual control remains available if accessibility is absent.
                    self._provider = None
        return self

    def disconnect(self):
        if self._provider:
            self._provider.disconnect()
            self._provider = None
        if self._connected:
            self.driver.disconnect()
            self._connected = False

    def __enter__(self): return self.connect()
    def __exit__(self, exc_type, exc, tb): self.disconnect()

    def screenshot(self, output: str | Path | None = None):
        self._require_connected()
        return self.driver.screenshot(output)

    def observe(self, screenshot_path: str | Path | None = None, include_elements=True, max_depth=12):
        self._require_connected()
        image = self.driver.screenshot(screenshot_path)
        active = self.driver.get_active_window()
        windows = self.driver.get_windows()
        width, height = image.size
        observation_id = str(uuid4())
        elements, notes = [], []
        if include_elements:
            if self._provider:
                try:
                    raw = self._provider.enumerate(
                        window_id=active.id if active and self.driver.name == "windows" else None,
                        max_depth=max_depth,
                    )
                    elements = self._tokens.reset(observation_id, raw)
                except Exception as exc:
                    notes.append(f"Accessibility enumeration unavailable: {exc}")
            else:
                notes.append("Accessibility provider unavailable; visual screenshot and input remain available.")
        else:
            self._tokens.reset(observation_id, [])
        self._last_observation_id = observation_id
        return Observation(
            observation_id=observation_id, platform=self.driver.name,
            session_type=getattr(self.driver, "session_type", None),
            active_window=active, windows=windows, elements=elements,
            screenshot=ScreenshotRef(path=str(screenshot_path) if screenshot_path else None,
                                     width=width, height=height),
            notes=notes,
        )

    def windows(self): self._require_connected(); return self.driver.get_windows()
    def active_window(self): self._require_connected(); return self.driver.get_active_window()
    def focus_window(self, window_id): self._require_connected(); return self.driver.focus_window(window_id)
    def click(self, x, y, button="left"): self._require_connected(); return self.driver.click(x, y, button)
    def move(self, x, y): self._require_connected(); return self.driver.move(x, y)
    def scroll(self, dx=0, dy=0): self._require_connected(); return self.driver.scroll(dx, dy)
    def type_text(self, text): self._require_connected(); return self.driver.type_text(text)
    def press_key(self, key): self._require_connected(); return self.driver.press_key(key)

    def click_element(self, element_id: str):
        self._invoke_element(element_id, "click")

    def focus_element(self, element_id: str):
        self._invoke_element(element_id, "focus")

    def set_element_value(self, element_id: str, value: str):
        self._invoke_element(element_id, "set_value", value)

    def _invoke_element(self, element_id, action, value=None):
        self._require_connected()
        if not self._provider:
            raise UnsupportedOperationError("Accessibility is unavailable; use coordinate-based input.")
        element = self._tokens.resolve(element_id)
        if action not in element.actions:
            raise UnsupportedOperationError(f"Element does not advertise action {action!r}.")
        self._provider.invoke(element, action, value)

    def _require_connected(self):
        if not self._connected:
            raise RuntimeError("Computer is not connected. Use connect() or a context manager.")
