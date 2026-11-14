from __future__ import annotations

import re

from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.target import TargetKind, UITarget


_COLOR_NAMES = {
    "black", "gray", "grey", "white", "red", "orange", "yellow", "green",
    "blue", "purple", "violet", "brown", "pink", "cyan", "magenta",
}
_SHAPE_WORDS = {
    "ellipse", "oval", "rectangle", "square", "triangle", "polygon", "line",
    "curve", "rounded rectangle", "diamond", "pentagon", "hexagon",
}
_TOOL_WORDS = {
    "pencil", "brush", "eraser", "fill", "bucket", "text", "select",
    "eyedropper", "magnifier", "crop", "spray", "color picker",
}


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value[:72] or "unnamed"


def _application_prefix(observation: Observation) -> str:
    window = observation.active_window
    identity = f"{window.title if window else ''} {window.process_name if window else ''}".casefold()
    if "paint" in identity or "mspaint" in identity:
        return "paint"
    if "photoshop" in identity:
        return "photoshop"
    return "desktop"


def _classify(role: str, name: str) -> TargetKind:
    value = f"{role} {name}".casefold()
    label = name.casefold().strip()
    if any(word in label for word in _SHAPE_WORDS):
        return "shape"
    if label in _COLOR_NAMES or any(f" {color} " in f" {label} " for color in _COLOR_NAMES):
        return "color"
    if any(word in label for word in _TOOL_WORDS):
        return "tool"
    if "canvas" in value or "drawing area" in value:
        return "canvas"
    if "menu" in role.casefold():
        return "menu"
    if "edit" in role.casefold() or "text" in role.casefold():
        return "field"
    if "button" in role.casefold():
        return "button"
    return "control"


class AccessibilityTargetDetector:
    """Convert named accessibility elements into screenshot-scoped named targets."""

    def detect(self, observation: Observation) -> list[UITarget]:
        prefix = _application_prefix(observation)
        targets: list[UITarget] = []
        used_ids: set[str] = set()
        for element in observation.elements:
            if not element.visible or not element.bounds:
                continue
            label = (element.name or element.value or element.automation_id or element.role).strip()
            if not label or element.bounds.width <= 0 or element.bounds.height <= 0:
                continue
            kind = _classify(element.role, label)
            slug = _slug(element.automation_id or label)
            target_id = f"{prefix}.{kind}.{slug}"
            if target_id in used_ids:
                target_id = f"{target_id}.{_slug(element.id)}"
            used_ids.add(target_id)
            targets.append(UITarget(
                target_id=target_id,
                label=label,
                kind=kind,
                bounds=element.bounds,
                observation_id=observation.observation_id,
                confidence=1.0,
                source="accessibility",
                enabled=element.enabled,
                visible=element.visible,
                metadata={
                    "element_id": element.id,
                    "role": element.role,
                    "automation_id": element.automation_id,
                    "class_name": element.class_name,
                    "parent_name": element.parent_name,
                    "actions": element.actions,
                },
            ))
        return targets
