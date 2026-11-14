from __future__ import annotations

from PIL import Image, ImageChops

from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.core.selector import matches
from qwencoder_cua.models.observation import Observation


def _verify_screen_changed(previous_path: str | None, current_path: str | None,
                           min_fraction: float = 0.01, pixel_delta: int = 16) -> tuple[bool, str]:
    if not previous_path or not current_path:
        return False, "Screen-change verification needs before and after screenshots."
    if not 0.0 <= min_fraction <= 1.0:
        return False, "screen_changed.min_fraction must be between 0 and 1."
    try:
        with Image.open(previous_path) as before_image, Image.open(current_path) as after_image:
            before = before_image.convert("RGB").resize((64, 64))
            after = after_image.convert("RGB").resize((64, 64))
            difference = ImageChops.difference(before, after)
            changed = sum(1 for pixel in difference.getdata() if max(pixel) >= pixel_delta)
            fraction = changed / (64 * 64)
    except (OSError, ValueError) as exc:
        return False, f"Could not compare screenshots: {exc}"
    ok = fraction >= min_fraction
    return ok, (
        f"Changed pixels: {fraction:.1%} ({changed}/4096 samples; "
        f"required {min_fraction:.1%})."
    )


def verify_observation(observation: Observation, expectation: dict,
                       previous_screenshot_path: str | None = None) -> tuple[bool, str]:
    """Evaluate every declared postcondition; all conditions must pass."""
    if not expectation:
        return False, "Postcondition is empty."

    checks: list[tuple[bool, str]] = []

    if "active_window_title_contains" in expectation:
        needle = str(expectation["active_window_title_contains"]).casefold()
        title = observation.active_window.title if observation.active_window else ""
        ok = needle in (title or "").casefold()
        checks.append((ok, "Active window title matches." if ok else
                       f"Window title {title!r} did not match."))

    if "screen_changed" in expectation:
        config = expectation["screen_changed"]
        ok, message = _verify_screen_changed(
            previous_screenshot_path,
            observation.screenshot.path if observation.screenshot else None,
            float(config.get("min_fraction", 0.01)),
            int(config.get("pixel_delta", 16)),
        )
        checks.append((ok, message))

    semantic_keys = {"element_absent", "element_present", "element_value"}
    requested_semantic = semantic_keys.intersection(expectation)
    if requested_semantic:
        if not observation.accessibility_available:
            checks.append((False, "Accessibility observation unavailable; semantic state cannot be verified."))
        else:
            if "element_absent" in expectation:
                selector = ElementSelector.model_validate(expectation["element_absent"])
                found = any(matches(item, selector) for item in observation.elements)
                checks.append((not found, "Element is absent." if not found else "Element is still present."))
            if "element_present" in expectation:
                selector = ElementSelector.model_validate(expectation["element_present"])
                found = any(matches(item, selector) for item in observation.elements)
                checks.append((found, "Element is present." if found else "Element was not found."))
            if "element_value" in expectation:
                spec = expectation["element_value"]
                selector = ElementSelector.model_validate(spec["selector"])
                found = [item for item in observation.elements if matches(item, selector)]
                if len(found) != 1:
                    checks.append((False, f"Expected one matching element; found {len(found)}."))
                else:
                    ok = found[0].value == spec.get("equals")
                    checks.append((ok, "Element value matches." if ok else
                                   f"Observed value {found[0].value!r}."))

    unsupported = set(expectation) - {
        "active_window_title_contains", "screen_changed",
        "element_absent", "element_present", "element_value",
    }
    if unsupported:
        checks.append((False, f"Unsupported postconditions: {sorted(unsupported)}."))
    if not checks:
        return False, "No supported postcondition was supplied."

    verified = all(item[0] for item in checks)
    return verified, " ".join(item[1] for item in checks)
