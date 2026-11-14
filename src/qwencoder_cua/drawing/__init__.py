"""Deterministic geometry, normalized scene planning and verified drawing execution."""

from qwencoder_cua.drawing.executor import DrawingExecutor
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
    "CanvasRegion", "DrawingExecutor", "ResolvedScene", "bezier_curve",
    "canvas_from_target", "ellipse_points", "polygon_points", "resolve_scene",
]
