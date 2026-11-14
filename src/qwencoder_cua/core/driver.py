from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from math import ceil, hypot
from time import sleep
from typing import Any, Sequence

from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


class BaseDriver(ABC):
    """Platform driver contract. Implementations control only the current user session."""

    name: str = "base"

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        raise NotImplementedError

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def screenshot(self, output: str | Path | None = None) -> Any:
        """Return a PIL Image; optionally save it to output."""
        raise NotImplementedError

    @abstractmethod
    def get_windows(self) -> list[WindowInfo]:
        raise NotImplementedError

    @abstractmethod
    def get_active_window(self) -> WindowInfo | None:
        raise NotImplementedError

    @abstractmethod
    def focus_window(self, window_id: str) -> None:
        raise NotImplementedError

    def capture_window(
        self, window_id: str, output: str | Path | None = None
    ) -> tuple[Any, tuple[int, int, int, int]]:
        """Capture a window client area and return image plus (screen_x, screen_y, width, height)."""
        raise NotImplementedError(
            f"Window-only screenshot capture is not supported by {self.name}."
        )

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError

    @abstractmethod
    def move(self, x: int, y: int) -> None:
        raise NotImplementedError

    def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError("Held mouse-button input is not supported by this driver.")

    def mouse_up(self, button: str = "left") -> None:
        raise NotImplementedError("Held mouse-button input is not supported by this driver.")

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             button: str = "left", duration_seconds: float = 0.5) -> None:
        self.draw_path(
            [(start_x, start_y), (end_x, end_y)],
            button=button,
            duration_seconds=duration_seconds,
        )

    def draw_path(self, points: Sequence[tuple[int, int]], button: str = "left",
                  duration_seconds: float = 1.0) -> None:
        """Draw a smooth polyline and always release the pointer button."""
        if button not in {"left", "middle", "right"}:
            raise ValueError(f"Unsupported mouse button: {button}")
        if not 0.05 <= duration_seconds <= 10.0:
            raise ValueError("duration_seconds must be between 0.05 and 10 seconds.")
        normalized = [(int(x), int(y)) for x, y in points]
        if not 2 <= len(normalized) <= 64:
            raise ValueError("A drawing path must contain between 2 and 64 points.")
        if any(x < 0 or y < 0 for x, y in normalized):
            raise ValueError("Drawing path coordinates must not be negative.")

        segments = []
        total_samples = 0
        for start, end in zip(normalized, normalized[1:]):
            distance = hypot(end[0] - start[0], end[1] - start[1])
            count = max(1, ceil(distance / 6.0))
            total_samples += count
            segments.append((start, end, count))
        if total_samples > 4096:
            raise ValueError("Drawing path is too long (more than 4096 pointer samples).")

        delay = duration_seconds / max(1, total_samples)
        pressed = False
        try:
            pressed = True
            self.mouse_down(*normalized[0], button=button)
            for start, end, count in segments:
                for index in range(1, count + 1):
                    ratio = index / count
                    x = round(start[0] + (end[0] - start[0]) * ratio)
                    y = round(start[1] + (end[1] - start[1]) * ratio)
                    self.move(x, y)
                    if delay:
                        sleep(delay)
        finally:
            if pressed:
                self.mouse_up(button=button)

    @abstractmethod
    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def press_key(self, key: str) -> None:
        raise NotImplementedError

    def get_accessibility_tree(self, window_id: str | None = None) -> list[dict]:
        raise NotImplementedError("Accessibility adapter is not implemented for this backend.")

    def get_clipboard(self) -> str:
        raise NotImplementedError("Clipboard is not supported by this backend.")

    def set_clipboard(self, text: str) -> None:
        raise NotImplementedError("Clipboard is not supported by this backend.")

    def launch_application(self, command: str, args: list[str] | None = None) -> int:
        raise NotImplementedError("Application launch is not supported by this backend.")
