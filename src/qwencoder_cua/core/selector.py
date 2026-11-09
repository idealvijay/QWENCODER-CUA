from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.core.exceptions import AmbiguousElementError, CUAError

def matches(element: UIElement, selector: ElementSelector) -> bool:
    if selector.visible_only and not element.visible:
        return False
    if selector.enabled_only and not element.enabled:
        return False
    for key in ("role", "name", "automation_id", "class_name", "value", "parent_name"):
        expected = getattr(selector, key)
        if expected is not None and getattr(element, key) != expected:
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
