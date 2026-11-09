"""Small path builders for application-independent drawing."""

from __future__ import annotations

from math import cos, pi, sin


def circle_path(
    center_x: int,
    center_y: int,
    radius: int,
    segments: int = 48,
) -> list[tuple[int, int]]:
    """Return a closed polyline approximating a circle in desktop pixels."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    if not 8 <= segments <= 128:
        raise ValueError("segments must be between 8 and 128")
    return [
        (
            round(center_x + radius * cos(2 * pi * index / segments)),
            round(center_y + radius * sin(2 * pi * index / segments)),
        )
        for index in range(segments + 1)
    ]


def rectangle_path(
    left: int,
    top: int,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Return a closed five-point rectangle polyline in desktop pixels."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    right, bottom = left + width, top + height
    return [
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
        (left, top),
    ]
