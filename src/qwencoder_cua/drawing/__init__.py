"""Deterministic geometry and normalized scene planning."""

from qwencoder_cua.drawing.geometry import (
    bezier_curve,
    ellipse_points,
    polygon_points,
)
from qwencoder_cua.drawing.scene_resolver import (
    CanvasRegion,
    ResolvedScene,
    canvas_from_target,
    resolve_scene,
)

__all__ = [
    "CanvasRegion", "ResolvedScene", "bezier_curve", "canvas_from_target",
    "ellipse_points", "polygon_points", "resolve_scene",
]
