from __future__ import annotations
import os
from qwencoder_cua.accessibility.base import AccessibilityProvider
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect

class LinuxATSPIProvider(AccessibilityProvider):
    """Linux accessibility adapter using AT-SPI2 Python bindings."""
    def __init__(self):
        self._atspi = None
        self._objects: dict[str, object] = {}

    def connect(self):
        if os.name != "posix":
            raise DriverUnavailableError("AT-SPI provider requires Linux.")
        try:
            import pyatspi
            self._atspi = pyatspi
        except Exception as exc:
            raise DriverUnavailableError(
                "AT-SPI bindings are unavailable. Install at-spi2-core and the "
                "distribution-provided pyatspi Python bindings."
            ) from exc

    def disconnect(self):
        self._objects.clear()
        self._atspi = None

    def enumerate(self, window_id=None, max_depth=12):
        if self._atspi is None:
            raise RuntimeError("AT-SPI provider is not connected.")
        self._objects.clear()
        desktop = self._atspi.Registry.getDesktop(0)
        result = []
        counter = 0

        def walk(obj, depth, parent_id=None, parent_name=None):
            nonlocal counter
            if obj is None or depth > max_depth:
                return
            try:
                role = obj.getRoleName() or "unknown"
                name = obj.name or None
                state = obj.getState()
                enabled = state.contains(self._atspi.STATE_ENABLED)
                visible = state.contains(self._atspi.STATE_VISIBLE) or state.contains(self._atspi.STATE_SHOWING)
                focused = state.contains(self._atspi.STATE_FOCUSED)
                bounds = None
                try:
                    ext = obj.queryComponent().getExtents(self._atspi.DESKTOP_COORDS)
                    bounds = Rect(x=int(ext.x), y=int(ext.y), width=int(ext.width), height=int(ext.height))
                except Exception:
                    pass
                value = None
                try:
                    value = str(obj.queryValue().currentValue)
                except Exception:
                    try:
                        text_iface = obj.queryText()
                        value = text_iface.getText(0, text_iface.characterCount)
                    except Exception:
                        pass
                raw_id = f"atspi:{counter}"
                counter += 1
                self._objects[raw_id] = obj
                actions = ["focus"] if enabled else []
                try:
                    if enabled and obj.queryAction().nActions:
                        actions.append("click")
                except Exception:
                    pass
                try:
                    obj.queryEditableText()
                    if enabled:
                        actions.append("set_value")
                except Exception:
                    pass
                attributes = {}
                try:
                    attributes = obj.getAttributes()
                except Exception:
                    pass
                result.append(UIElement(
                    id=raw_id, role=str(role).lower(), name=name, value=value, bounds=bounds,
                    enabled=enabled, visible=visible, focused=focused, actions=actions,
                    parent_id=parent_id, parent_name=parent_name,
                    automation_id=attributes.get("id") or None, depth=depth,
                ))
                for index in range(obj.getChildCount()):
                    try:
                        walk(obj.getChildAtIndex(index), depth + 1, raw_id, name)
                    except Exception:
                        continue
            except Exception:
                return

        for index in range(desktop.getChildCount()):
            try:
                walk(desktop.getChildAtIndex(index), 0)
            except Exception:
                continue
        return result

    def invoke(self, element, action, value=None):
        obj = self._objects.get(element.id)
        if obj is None:
            raise UnsupportedOperationError("AT-SPI target is stale; enumerate the tree again.")
        try:
            if action == "focus":
                obj.queryComponent().grabFocus()
            elif action == "click":
                obj.queryAction().doAction(0)
            elif action == "set_value":
                if value is None:
                    raise ValueError("set_value requires a value.")
                obj.queryEditableText().setTextContents(value)
            else:
                raise UnsupportedOperationError(f"Unsupported AT-SPI action: {action}")
        except UnsupportedOperationError:
            raise
        except Exception as exc:
            raise UnsupportedOperationError(f"AT-SPI {action} failed: {exc}") from exc
