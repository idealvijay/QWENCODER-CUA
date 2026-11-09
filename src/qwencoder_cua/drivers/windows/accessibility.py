from __future__ import annotations
import os
from qwencoder_cua.accessibility.base import AccessibilityProvider
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect

class WindowsUIAProvider(AccessibilityProvider):
    """Microsoft UI Automation adapter backed by pywinauto's UIA backend."""
    def __init__(self):
        self._desktop = None
        self._wrappers: dict[str, object] = {}

    def connect(self):
        if os.name != "nt":
            raise DriverUnavailableError("Windows UIA provider requires Windows.")
        try:
            from pywinauto import Desktop
            self._desktop = Desktop(backend="uia")
        except Exception as exc:
            raise DriverUnavailableError(f"Could not initialize Windows UI Automation: {exc}") from exc

    def disconnect(self):
        self._wrappers.clear()
        self._desktop = None

    def enumerate(self, window_id=None, max_depth=12):
        if self._desktop is None:
            raise RuntimeError("Windows UIA provider is not connected.")
        self._wrappers.clear()
        try:
            root = self._desktop.window(handle=int(window_id)) if window_id else self._desktop.get_active()
            root_wrapper = root.wrapper_object()
            wrappers = [root_wrapper] + root_wrapper.descendants()
        except Exception as exc:
            raise UnsupportedOperationError(f"UIA tree enumeration failed: {exc}") from exc
        elements = []
        for index, wrapper in enumerate(wrappers):
            try:
                info = wrapper.element_info
                depth = int(getattr(info, "depth", 0) or 0)
                if depth > max_depth:
                    continue
                rect = info.rectangle
                bounds = Rect(x=rect.left, y=rect.top, width=max(0, rect.width()), height=max(0, rect.height()))
                raw_id = f"uia:{index}"
                self._wrappers[raw_id] = wrapper
                enabled = bool(getattr(info, "enabled", True))
                control_type = str(getattr(info, "control_type", "unknown") or "unknown").lower()
                actions = ["focus"] if enabled else []
                if enabled and control_type not in {"text", "titlebar", "separator", "image"}:
                    actions.append("click")
                if enabled and control_type in {"edit", "document", "combobox"}:
                    actions.append("set_value")
                elements.append(UIElement(
                    id=raw_id, role=control_type, name=getattr(info, "name", None) or None,
                    bounds=bounds, enabled=enabled, visible=bool(getattr(info, "visible", True)),
                    focused=bool(getattr(info, "has_keyboard_focus", False)), actions=actions,
                    automation_id=getattr(info, "automation_id", None) or None,
                    class_name=getattr(info, "class_name", None) or None,
                    native_id=str(getattr(info, "handle", "") or "") or None,
                    depth=depth,
                ))
            except Exception:
                continue
        return elements

    def invoke(self, element, action, value=None):
        wrapper = self._wrappers.get(element.id)
        if wrapper is None:
            raise UnsupportedOperationError("UIA target is stale; enumerate the tree again.")
        if not element.enabled:
            raise UnsupportedOperationError("Cannot interact with a disabled element.")
        try:
            if action == "click":
                wrapper.click_input()
            elif action == "focus":
                wrapper.set_focus()
            elif action == "set_value":
                if value is None:
                    raise ValueError("set_value requires a value.")
                wrapper.set_edit_text(value)
            else:
                raise UnsupportedOperationError(f"Unsupported UIA action: {action}")
        except UnsupportedOperationError:
            raise
        except Exception as exc:
            raise UnsupportedOperationError(f"UIA {action} failed: {exc}") from exc
