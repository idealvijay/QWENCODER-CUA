"""Coordinate helpers shared by vision prompts and task execution."""

from __future__ import annotations

PLANNER_IMAGE_MAX_WIDTH = 448
PLANNER_IMAGE_MAX_HEIGHT = 448


def planner_image_dimensions(
    width: int,
    height: int,
    max_width: int = PLANNER_IMAGE_MAX_WIDTH,
    max_height: int = PLANNER_IMAGE_MAX_HEIGHT,
) -> tuple[int, int]:
    """Return the aspect-preserving, low-resolution dimensions sent to vision planners."""
    if min(width, height, max_width, max_height) <= 0:
        raise ValueError("Screenshot and maximum dimensions must be positive.")
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))
