"""Coordinate helpers shared by vision prompts and task execution."""

from __future__ import annotations


def planner_image_dimensions(
    width: int,
    height: int,
    max_width: int = 1280,
    max_height: int = 800,
) -> tuple[int, int]:
    """Return the aspect-preserving dimensions used for planner screenshots."""
    if min(width, height, max_width, max_height) <= 0:
        raise ValueError("Screenshot and maximum dimensions must be positive.")
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))
