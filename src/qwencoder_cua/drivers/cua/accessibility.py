from __future__ import annotations

from qwencoder_cua.accessibility.base import AccessibilityProvider
from qwencoder_cua.core.exceptions import UnsupportedOperationError
from qwencoder_cua.models.element import UIElement


class CuaAccessibilityProvider(AccessibilityProvider):
    """Expose Cua Driver's snapshot-bound element tokens to Computer."""

    def __init__(self, driver):
        self.driver = driver

    def connect(self) -> None:
        # The Cua Driver runtime is owned and connected by CuaDriverBackend.
        return None

    def disconnect(self) -> None:
        # The Cua Driver runtime is owned and disconnected by CuaDriverBackend.
        return None

    def enumerate(self, window_id: str | None = None, max_depth: int = 12) -> list[UIElement]:
        elements = self.driver.accessibility_elements(window_id)
        return [element for element in elements if element.depth <= max_depth]

    def invoke(self, element: UIElement, action: str, value: str | None = None) -> None:
        if action not in element.actions:
            raise UnsupportedOperationError(
                f"Cua Driver element does not advertise action {action!r}."
            )
        self.driver.invoke_element(element, action, value)
