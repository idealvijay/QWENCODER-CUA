from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from qwencoder_cua.core.registry import create_driver
from qwencoder_cua.models.observation import Observation, ScreenshotRef
from qwencoder_cua.accessibility.tokens import ElementTokenStore
from qwencoder_cua.core.exceptions import UnsupportedOperationError
from qwencoder_cua.core.selector import select_unique
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.models.action import ActionOutcome
from qwencoder_cua.execution.verifier import verify_observation


class Computer:
    """Local desktop facade: visual controls plus optional accessibility semantics."""

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
                    self._provider = None
        return self

    def disconnect(self):
        if self._provider:
            self._provider.disconnect()
            self._provider = None
        if self._connected:
            self.driver.disconnect()
            self._connected = False
        self._tokens.reset(str(uuid4()), [])
        self._last_observation_id = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()

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
        raw_elements = []
        notes = []
        accessibility_available = False
        if include_elements and self._provider:
            try:
                raw_elements = self._provider.enumerate(
                    window_id=active.id if active and self.driver.name == "windows" else None,
                    max_depth=max_depth,
                )
                accessibility_available = True
            except Exception as exc:
                notes.append(f"Accessibility enumeration unavailable: {exc}")
        elif include_elements:
            notes.append("Accessibility provider unavailable; visual screenshot and input remain available.")
        # Even an empty/failed accessibility observation invalidates all previous element IDs.
        elements = self._tokens.reset(observation_id, raw_elements)
        self._last_observation_id = observation_id
        return Observation(
            observation_id=observation_id,
            platform=self.driver.name,
            session_type=getattr(self.driver, "session_type", None),
            active_window=active,
            windows=windows,
            elements=elements,
            accessibility_available=accessibility_available,
            screenshot=ScreenshotRef(
                path=str(screenshot_path) if screenshot_path else None,
                width=width, height=height
            ),
            notes=notes,
        )

    def windows(self):
        self._require_connected()
        return self.driver.get_windows()

    def active_window(self):
        self._require_connected()
        return self.driver.get_active_window()

    def focus_window(self, window_id):
        self._require_connected()
        return self.driver.focus_window(window_id)

    def click(self, x, y, button="left"):
        self._require_connected()
        return self.driver.click(x, y, button)

    def move(self, x, y):
        self._require_connected()
        return self.driver.move(x, y)

    def mouse_down(self, x, y, button="left"):
        self._require_connected()
        return self.driver.mouse_down(x, y, button)

    def mouse_up(self, button="left"):
        self._require_connected()
        return self.driver.mouse_up(button)

    def drag(self, start_x, start_y, end_x, end_y, button="left", duration_seconds=0.5):
        self._require_connected()
        return self.driver.drag(
            start_x, start_y, end_x, end_y,
            button=button, duration_seconds=duration_seconds,
        )

    def draw_path(self, points, button="left", duration_seconds=1.0):
        self._require_connected()
        return self.driver.draw_path(points, button=button, duration_seconds=duration_seconds)

    def scroll(self, dx=0, dy=0):
        self._require_connected()
        return self.driver.scroll(dx, dy)

    def type_text(self, text):
        self._require_connected()
        return self.driver.type_text(text)

    def press_key(self, key):
        self._require_connected()
        return self.driver.press_key(key)

    def click_element(self, element_id: str):
        self._invoke_element(element_id, "click")

    def focus_element(self, element_id: str):
        self._invoke_element(element_id, "focus")

    def set_element_value(self, element_id: str, value: str):
        self._invoke_element(element_id, "set_value", value)

    def find_element(self, selector: ElementSelector | dict):
        self._require_connected()
        if self._last_observation_id is None:
            raise RuntimeError("Call observe() before find_element().")
        if isinstance(selector, dict):
            selector = ElementSelector.model_validate(selector)
        return select_unique(self._tokens.elements(), selector)

    def reidentify(self, selector: ElementSelector | dict, max_depth: int = 12):
        """Refresh accessibility data and return a new short-lived element token."""
        if isinstance(selector, dict):
            selector = ElementSelector.model_validate(selector)
        observation = self.observe(include_elements=True, max_depth=max_depth)
        if not observation.accessibility_available:
            raise UnsupportedOperationError("Cannot re-identify without an accessibility observation.")
        return select_unique(observation.elements, selector)

    def act_and_verify(self, element_id: str, action: str, expectation: dict,
                       value: str | None = None, timeout: float = 3.0,
                       poll_interval: float = 0.25) -> ActionOutcome:
        """Invoke an action and poll fresh observations until its postcondition is true."""
        self._require_connected()
        before_id = self._last_observation_id
        started = datetime.now(timezone.utc)
        self._invoke_element(element_id, action, value)
        deadline = monotonic() + max(0.0, timeout)
        after = None
        verified, message = False, "Verification did not run."
        while True:
            after = self.observe(include_elements=True)
            verified, message = verify_observation(after, expectation)
            if verified or monotonic() >= deadline:
                break
            sleep(max(0.01, poll_interval))
        return ActionOutcome(
            action=action, element_id=element_id, success=True, verified=verified,
            verification=message, before_observation_id=before_id,
            after_observation_id=after.observation_id if after else None,
            started_at=started, completed_at=datetime.now(timezone.utc),
            details={"expectation": expectation, "timeout_seconds": timeout},
        )

    def _invoke_element(self, element_id, action, value=None):
        self._require_connected()
        if not self._provider:
            raise UnsupportedOperationError("Accessibility is unavailable; use coordinate-based input.")
        element = self._tokens.resolve(element_id)
        if action not in element.actions:
            raise UnsupportedOperationError(f"Element does not advertise action {action!r}.")
        # Provider adapters maintain their own object map; restore the provider-side ID.
        backend_element = self._tokens.resolve_provider_element(element_id)
        self._provider.invoke(backend_element, action, value)

    def _require_connected(self):
        if not self._connected:
            raise RuntimeError("Computer is not connected. Use connect() or a context manager.")
