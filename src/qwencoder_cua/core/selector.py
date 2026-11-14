from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.core.exceptions import AmbiguousElementError, CUAError


_NON_INTERACTIVE_TOOL_ROLES = {
    "window", "pane", "group", "toolbar", "tool bar", "menu",
    "text", "titlebar", "separator", "image", "unknown",
}
_BUTTON_ROLES = {
    "button", "radio button", "split button", "toggle button",
}
_NAME_ALIASES = {
    "ellipse": {"oval"},
    "oval": {"ellipse"},
}


def _matches_role(element: UIElement, expected: str) -> bool:
    """Match native roles and the planner's constrained semantic role aliases."""
    actual = (element.role or "").strip().casefold()
    expected = expected.strip().casefold()
    if actual == expected:
        return True

    # UI Automation exposes shape choices as radio buttons in some app versions.
    # Accept those native button subtypes only when the element is actually clickable.
    if expected == "button":
        return actual in _BUTTON_ROLES and "click" in element.actions

    # "tool" describes the purpose of a control, not a Windows UIA ControlType.
    # Keep the alias constrained to clickable controls.
    return (
        expected == "tool"
        and "click" in element.actions
        and actual not in _NON_INTERACTIVE_TOOL_ROLES
    )


def _name_alternatives(value: str) -> set[str]:
    """Split combined accessibility labels such as 'Ellipse/Oval' into exact names."""
    return {
        part.strip().casefold()
        for part in value.split("/")
        if part.strip()
    }


def _matches_name(actual: str | None, expected: str) -> bool:
    if not actual:
        return False

    actual_names = _name_alternatives(actual)
    expected_names = _name_alternatives(expected)
    if actual_names.intersection(expected_names):
        return True

    # Ellipse and Oval are standard aliases for the same Paint shape control.
    for actual_name in actual_names:
        if _NAME_ALIASES.get(actual_name, set()).intersection(expected_names):
            return True
    for expected_name in expected_names:
        if _NAME_ALIASES.get(expected_name, set()).intersection(actual_names):
            return True
    return False


def matches(element: UIElement, selector: ElementSelector) -> bool:
    if selector.visible_only and not element.visible:
        return False
    if selector.enabled_only and not element.enabled:
        return False
    for key in ("role", "name", "automation_id", "class_name", "value", "parent_name"):
        expected = getattr(selector, key)
        if expected is not None:
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
