from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

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

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError

    @abstractmethod
    def move(self, x: int, y: int) -> None:
        raise NotImplementedError

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
