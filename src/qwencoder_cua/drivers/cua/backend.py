from __future__ import annotations

import asyncio
import base64
import importlib
import io
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Sequence

import psutil
from PIL import Image

from qwencoder_cua.core.driver import BaseDriver
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.window import WindowInfo


class CuaDriverBackend(BaseDriver):
    """Experimental adapter over the Rust-backed Cua Driver Python SDK.

    The SDK owns capture, Windows UI Automation, target tokens and native input.
    This class only adapts its typed API to QWENCODER's synchronous BaseDriver
    contract. The native QWENCODER backend remains the default.
    """

    name = "cua"

    # Cua Driver can capture a specific window without activating it. Input
    # delivery is still explicit per action (background for element clicks,
    # foreground for coordinate clicks).
    background_window_capture = True

    def __init__(self, operation_timeout: float = 30.0):
        self.operation_timeout = operation_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._sdk: Any = None
        self._runtime: Any = None
        self._last_window_state: Any = None
        self._selected_window: WindowInfo | None = None
        self._connected = False

    @property
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            screenshot=True,
            window_enumeration=True,
            window_focus=True,
            mouse_input=True,
            keyboard_input=True,
            accessibility=True,
            clipboard=False,
            global_input=True,
            background_input=True,
        )

    def connect(self) -> None:
        if self._connected:
            return
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run_loop,
            name="qwencoder-cua-driver",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=self.operation_timeout):
            raise DriverUnavailableError("Timed out starting the Cua Driver runtime.")
        if self._startup_error is not None:
            raise DriverUnavailableError(
                'Could not start Cua Driver. Install the optional dependency with '
                'pip install -e ".[windows,cua]". '
                f"Underlying error: {self._startup_error}"
            ) from self._startup_error
        self._connected = True

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._sdk = importlib.import_module("cua_driver")
            self._runtime = self._sdk.CuaDriver.create()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def _require_connected(self) -> None:
        if not self._connected or self._loop is None or self._runtime is None:
            raise RuntimeError("Cua Driver backend is not connected.")

    def _call(self, method: str, *args: Any) -> Any:
        self._require_connected()
        operation = getattr(self._runtime, method)(*args)
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            return future.result(timeout=self.operation_timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise DriverUnavailableError(
                f"Cua Driver operation {method!r} timed out after "
                f"{self.operation_timeout:.1f}s. Its input outcome may be unknown; "
                "observe the target window before retrying."
            ) from exc

    def disconnect(self) -> None:
        if self._runtime is not None and self._loop is not None:
            try:
                self._call("shutdown")
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._connected = False
        self._runtime = None
        self._sdk = None
        self._loop = None
        self._thread = None
        self._last_window_state = None
        self._selected_window = None

    def _list_apps(self) -> list[Any]:
        output = self._call("list_apps", self._sdk.ListAppsInput())
        return list(output.apps or [])

    @staticmethod
    def _process_name(pid: int | None, app: Any | None = None) -> str | None:
        if pid is not None:
            try:
                return psutil.Process(pid).name()
            except (psutil.Error, OSError):
                pass
        launch_path = getattr(app, "launch_path", None) if app is not None else None
        return Path(launch_path).name if launch_path else None

    def get_windows(self) -> list[WindowInfo]:
        self._require_connected()
        apps = self._list_apps()
        apps_by_pid = {int(app.pid): app for app in apps}
        output = self._call(
            "list_windows",
            self._sdk.ListWindowsInput(pid=None, on_screen_only=None),
        )
        raw_windows = list(output.windows or [])

        active_pids = {
            int(app.pid) for app in apps
            if bool(getattr(app, "active", False)) and bool(getattr(app, "running", True))
        }
        active_candidates = [
            window for window in raw_windows
            if window.pid is not None
            and int(window.pid) in active_pids
            and bool(window.is_on_screen)
            and not bool(window.minimized)
        ]
        active_window_id = (
            int(active_candidates[0].window_id)
            if len(active_candidates) == 1
            else None
        )

        result: list[WindowInfo] = []
        for window in raw_windows:
            bounds = getattr(window, "bounds", None)
            box = None
            if bounds is not None:
                box = (
                    round(bounds.x),
                    round(bounds.y),
                    round(bounds.width),
                    round(bounds.height),
                )
            pid = int(window.pid) if window.pid is not None else None
            app = apps_by_pid.get(pid) if pid is not None else None
            result.append(WindowInfo(
                id=str(window.window_id),
                title=window.title or "",
                process_id=pid,
                process_name=self._process_name(pid, app),
                visible=bool(window.is_on_screen),
                minimized=bool(window.minimized),
                bounds=box,
                is_active=(
                    active_window_id is not None
                    and int(window.window_id) == active_window_id
                ),
            ))
        return result

    def get_active_window(self) -> WindowInfo | None:
        active = [window for window in self.get_windows() if window.is_active]
        return active[0] if len(active) == 1 else None

    def focus_window(self, window_id: str) -> None:
        """Window capture is addressed directly; input focus is explicit per action."""
        self._require_connected()
        if not any(window.id == str(window_id) for window in self.get_windows()):
            raise UnsupportedOperationError(f"Unknown Cua Driver window ID: {window_id}")

    def _resolve_window(self, window_id: str) -> WindowInfo:
        matches = [window for window in self.get_windows() if window.id == str(window_id)]
        if len(matches) != 1:
            raise UnsupportedOperationError(
                f"Expected one window with ID {window_id!r}; found {len(matches)}."
            )
        return matches[0]

    def _window_state(self, window: WindowInfo, output: str | Path | None = None) -> Any:
        if window.process_id is None:
            raise UnsupportedOperationError("Cua Driver did not report a PID for the target window.")
        request = self._sdk.GetWindowStateInput(
            pid=int(window.process_id),
            window_id=int(window.id),
            session=None,
            query=None,
            include_accessibility_tree=True,
            include_screenshot=True,
            screenshot_out_file=str(output) if output is not None else None,
            max_elements=500,
            max_depth=18,
            max_dimension=None,
            max_image_dimension=0,
        )
        state = self._call("get_window_state", request)
        if getattr(state, "screenshot_frame_valid", True) is False:
            raise UnsupportedOperationError("Cua Driver returned an invalid window screenshot frame.")
        self._last_window_state = state
        self._selected_window = window
        return state

    @staticmethod
    def _image_from_state(state: Any, output: str | Path | None = None) -> Image.Image:
        if output is not None:
            path = Path(output)
            if path.exists() and path.stat().st_size:
                with Image.open(path) as source:
                    return source.convert("RGB").copy()
        images = list(getattr(state, "images", None) or [])
        if not images:
            raise DriverUnavailableError("Cua Driver did not return a screenshot image.")
        try:
            raw = base64.b64decode(images[0].data_base64, validate=True)
            with Image.open(io.BytesIO(raw)) as source:
                return source.convert("RGB").copy()
        except Exception as exc:
            raise DriverUnavailableError(f"Could not decode Cua Driver screenshot: {exc}") from exc

    def screenshot(self, output: str | Path | None = None) -> Image.Image:
        self._require_connected()
        request = self._sdk.GetDesktopStateInput(
            session=None,
            screenshot_out_file=str(output) if output is not None else None,
            max_image_dimension=0,
        )
        result = self._call("get_desktop_state", request)
        if getattr(result, "is_error", False):
            raise DriverUnavailableError(getattr(result, "text", "Desktop capture failed."))
        return self._image_from_state(result, output)

    def capture_window(
        self, window_id: str, output: str | Path | None = None
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        self._require_connected()
        window = self._resolve_window(window_id)
        if not window.visible or window.minimized:
            raise UnsupportedOperationError("The selected Cua Driver window is not visible.")
        state = self._window_state(window, output)
        image = self._image_from_state(state, output)
        if state.window_bounds is not None:
            bounds = state.window_bounds
            screen_bounds = (
                round(bounds.x), round(bounds.y),
                round(bounds.width), round(bounds.height),
            )
        elif window.bounds is not None:
            screen_bounds = window.bounds
        else:
            raise UnsupportedOperationError("Cua Driver did not return target-window bounds.")
        if image.size != (screen_bounds[2], screen_bounds[3]):
            raise UnsupportedOperationError(
                "Cua Driver screenshot size does not match the reported window bounds: "
                f"image={image.size}, bounds={screen_bounds[2:]}."
            )
        return image, screen_bounds

    def create_accessibility_provider(self):
        from qwencoder_cua.drivers.cua.accessibility import CuaAccessibilityProvider
        return CuaAccessibilityProvider(self)

    def accessibility_elements(self, window_id: str | None = None) -> list[UIElement]:
        self._require_connected()
        state = self._last_window_state
        if state is None or (
            window_id is not None and int(state.window_id) != int(window_id)
        ):
            if window_id is None:
                active = self.get_active_window()
                if active is None:
                    return []
                window_id = active.id
            self._window_state(self._resolve_window(window_id))
            state = self._last_window_state
        if getattr(state, "degraded", False) or getattr(state, "truncated", False):
            raise UnsupportedOperationError(
                "Cua Driver accessibility snapshot is degraded or truncated; refresh it "
                "or use screenshot-grounded coordinates."
            )

        elements = list(getattr(state, "elements", None) or [])
        by_index = {int(item.element_index): item for item in elements}
        normalized: list[UIElement] = []
        for item in elements:
            frame = getattr(item, "frame", None)
            bounds = None
            if frame is not None and frame.w > 0 and frame.h > 0:
                bounds = Rect(
                    x=round(frame.x), y=round(frame.y),
                    width=round(frame.w), height=round(frame.h),
                )
            parent = by_index.get(item.parent_index) if item.parent_index is not None else None
            token = getattr(item, "element_token", None)
            actions = [
                action for action in (getattr(item, "actions", None) or [])
                if action in {"click", "set_value"}
            ] if token else []
            normalized.append(UIElement(
                id=token or f"cua-index:{item.element_index}",
                role=item.role or "unknown",
                name=item.label or None,
                value=item.value,
                bounds=bounds,
                enabled=item.enabled is not False,
                visible=bounds is not None,
                focused=False,
                actions=actions,
                parent_id=(
                    getattr(parent, "element_token", None) if parent is not None else None
                ),
                parent_name=getattr(parent, "label", None) if parent is not None else None,
                native_id=token,
                depth=int(item.depth or 0),
            ))
        return normalized

    def _target(self):
        if self._selected_window is not None:
            return self._sdk.ActionTarget.WINDOW(
                pid=int(self._selected_window.process_id),
                window_id=int(self._selected_window.id),
            )
        return self._sdk.ActionTarget.DESKTOP(display_id="primary")

    @staticmethod
    def _check_result(result: Any, operation: str) -> Any:
        effect = getattr(result, "effect", None)
        if getattr(effect, "name", "").upper() == "REFUSED":
            detail = getattr(result, "summary", None) or getattr(result, "hint", None) or str(result)
            raise UnsupportedOperationError(f"Cua Driver refused {operation}: {detail}")
        if getattr(result, "is_error", False):
            raise UnsupportedOperationError(
                f"Cua Driver {operation} failed: {getattr(result, 'text', str(result))}"
            )
        return result

    def invoke_element(self, element: UIElement, action: str, value: str | None = None) -> None:
        self._require_connected()
        if self._selected_window is None:
            raise UnsupportedOperationError("No target window is bound for an accessibility action.")
        if action == "click":
            request = self._sdk.ClickInput(
                target=self._target(),
                position=self._sdk.ClickPosition.ELEMENT(element_token=element.id),
                delivery_mode=self._sdk.InputDeliveryMode.BACKGROUND,
                session=None,
                button=self._sdk.ClickButton.LEFT,
                count=1,
            )
            self._check_result(self._call("click", request), "accessibility click")
            return
        raise UnsupportedOperationError(
            f"Cua Driver adapter does not yet map accessibility action {action!r}."
        )

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._require_connected()
        button_value = {
            "left": self._sdk.ClickButton.LEFT,
            "right": self._sdk.ClickButton.RIGHT,
            "middle": self._sdk.ClickButton.MIDDLE,
        }.get(button)
        if button_value is None:
            raise ValueError(f"Unsupported mouse button: {button}")
        request = self._sdk.ClickInput(
            target=self._target(),
            position=self._sdk.ClickPosition.COORDINATES(x=float(x), y=float(y)),
            delivery_mode=self._sdk.InputDeliveryMode.FOREGROUND,
            session=None,
            button=button_value,
            count=1,
        )
        self._check_result(self._call("click", request), "coordinate click")

    def move(self, x: int, y: int) -> None:
        request = self._sdk.MoveCursorInput(
            x=float(x), y=float(y), target=self._target(), scope=None, session=None
        )
        self._check_result(self._call("move_cursor", request), "pointer move")

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int,
        button: str = "left", duration_seconds: float = 0.5,
    ) -> None:
        self._require_connected()
        button_value = {
            "left": self._sdk.ClickButton.LEFT,
            "right": self._sdk.ClickButton.RIGHT,
            "middle": self._sdk.ClickButton.MIDDLE,
        }.get(button)
        if button_value is None:
            raise ValueError(f"Unsupported mouse button: {button}")
        if not 0.0 <= duration_seconds <= 10.0:
            raise ValueError("duration_seconds must be between 0 and 10 seconds.")
        distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5
        request = self._sdk.DragInput(
            from_x=float(start_x),
            from_y=float(start_y),
            to_x=float(end_x),
            to_y=float(end_y),
            target=self._target() if self._selected_window is not None else None,
            scope=None,
            session=None,
            duration_ms=round(duration_seconds * 1000),
            steps=max(2, min(80, round(distance / 8))),
            button=button_value,
            modifier=None,
        )
        self._check_result(self._call("drag", request), "drag")

    def draw_path(
        self,
        points: Sequence[tuple[int, int]],
        button: str = "left",
        duration_seconds: float = 1.0,
    ) -> None:
        """Approximate a freehand path with short native drag segments.

        Cua Driver's stable typed Python SDK exposes drag gestures rather than
        held-button move events on Windows. Segments share exact endpoints; this
        is suitable for a backend spike but may produce joins in some apps.
        """
        normalized = [(int(x), int(y)) for x, y in points]
        if not 2 <= len(normalized) <= 64:
            raise ValueError("A drawing path must contain between 2 and 64 points.")
        if not 0.05 <= duration_seconds <= 10.0:
            raise ValueError("duration_seconds must be between 0.05 and 10 seconds.")
        per_segment = duration_seconds / (len(normalized) - 1)
        for start, end in zip(normalized, normalized[1:]):
            self.drag(*start, *end, button=button, duration_seconds=per_segment)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        self._require_connected()
        if dx:
            direction = (
                self._sdk.ScrollDirection.RIGHT
                if dx > 0 else self._sdk.ScrollDirection.LEFT
            )
            amount = abs(int(dx))
        elif dy:
            direction = (
                self._sdk.ScrollDirection.UP
                if dy > 0 else self._sdk.ScrollDirection.DOWN
            )
            amount = abs(int(dy))
        else:
            return
        request = self._sdk.ScrollInput(
            x=0.0,
            y=0.0,
            direction=direction,
            target=self._target(),
            scope=None,
            session=None,
            by=self._sdk.ScrollBy.LINE,
            amount=amount,
        )
        self._check_result(self._call("scroll", request), "scroll")

    def type_text(self, text: str) -> None:
        self._require_connected()
        request = self._sdk.TypeTextInput(
            text=text, target=self._target(), scope=None, session=None
        )
        self._check_result(self._call("type_text", request), "type text")

    def press_key(self, key: str) -> None:
        self._require_connected()
        request = self._sdk.PressKeyInput(
            key=key, target=self._target(), scope=None, session=None, modifiers=None
        )
        self._check_result(self._call("press_key", request), "press key")
