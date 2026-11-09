from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.core.selector import matches
from qwencoder_cua.models.observation import Observation

def verify_observation(observation: Observation, expectation: dict) -> tuple[bool, str]:
    """Check a declarative postcondition against a fresh desktop observation."""
    if "active_window_title_contains" in expectation:
        needle = str(expectation["active_window_title_contains"]).casefold()
        title = observation.active_window.title if observation.active_window else ""
        ok = needle in (title or "").casefold()
        return ok, "Active window title matches." if ok else f"Window title {title!r} did not match."
    if not observation.accessibility_available:
        return False, "Accessibility observation unavailable; semantic state cannot be verified."
    if "element_absent" in expectation:
        selector = ElementSelector.model_validate(expectation["element_absent"])
        found = any(matches(item, selector) for item in observation.elements)
        return not found, "Element is absent." if not found else "Element is still present."
    if "element_present" in expectation:
        selector = ElementSelector.model_validate(expectation["element_present"])
        found = any(matches(item, selector) for item in observation.elements)
        return found, "Element is present." if found else "Element was not found."
    if "element_value" in expectation:
        spec = expectation["element_value"]
        selector = ElementSelector.model_validate(spec["selector"])
        found = [item for item in observation.elements if matches(item, selector)]
        if len(found) != 1:
            return False, f"Expected one matching element; found {len(found)}."
        ok = found[0].value == spec.get("equals")
        return ok, "Element value matches." if ok else f"Observed value {found[0].value!r}."
    return False, "Unsupported or empty verification expectation."
