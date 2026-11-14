from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.core.exceptions import AmbiguousElementError, CUAError


_NON_INTERACTIVE_TOOL_ROLES = {
    "window", "pane", "group", "toolbar", "tool bar", "menu",
    "text", "titlebar", "separator", "image", "unknown",
}


def _matches_role(element: UIElement, expected: str) -> bool:
    """Match native accessibility roles and the planner's semantic tool alias."""
    actual = (element.role or "").strip().casefold()
    expected = expected.strip().casefold()
    if actual == expected:
        return True

    # "tool" describes the purpose of a control, not a Windows UIA ControlType.
    # Keep this alias constrained to clickable controls; the caller still requires
    # the other selector identity fields (normally an exact accessible name).
    return (
        expected == "tool"
        and "click" in element.actions
        and actual not in _NON_INTERACTIVE_TOOL_ROLES
    )


def _matches_name(actual: str | None, expected: str) -> bool:
    if actual == expected:
        return True

    # Vision models sometimes describe a control with a combined label such as
    # "Ellipse/Oval", while UI Automation exposes only one localized label.
    # Treat slash-separated terms in the requested label as exact alternatives.
    if "/" in expected and actual:
        alternatives = {
            part.strip().casefold()
            for part in expected.split("/")
            if part.strip()
        }
        return actual.strip().casefold() in alternatives
    return False


def matches(element: UIElement, selector: ElementSelector) -> bool:
    if selector.visible_only and not element.visible:
        return False
    if selector.enabled_only and not element.enabled:
        return False

    for key in ("role", "name", "automation_id", "class_name", "value", "parent_name"):
        expected = getattr(selector, key)
        if expected is None:
            continue
        actual = getattr(element, key)
        if key == "role":
            if not _matches_role(element, expected):
                return False
        elif key == "name":
            if not _matches_name(actual, expected):
                return False
        elif actual != expected:
            return False
    return True


def select_unique(elements: list[UIElement], selector: ElementSelector) -> UIElement:
    if not selector.has_identity():
        raise CUAError("ElementSelector needs at least one identity field.")
    found = [item for item in elements if matches(item, selector)]
    if not found:
        raise CUAError(f"No element matched selector: {selector.model_dump(exclude_none=True)}")
    if len(found) > 1:
        raise AmbiguousElementError(
            f"Selector matched {len(found)} elements; add automation_id or parent_name."
        )
    return found[0]
