from __future__ import annotations

from math import cos, pi, sin

from qwencoder_cua.models.scene import NormalizedPoint


def ellipse_points(
    center: NormalizedPoint,
    radius_x: float,
    radius_y: float,
    *,
    segments: int = 24,
) -> list[NormalizedPoint]:
    """Generate a closed, evenly sampled ellipse path in normalized canvas space."""
    if not 0.0 < radius_x <= 1.0 or not 0.0 < radius_y <= 1.0:
        raise ValueError("ellipse radii must be between 0 and 1")
    if not 12 <= segments <= 64:
        raise ValueError("segments must be between 12 and 64")
    points = [
        NormalizedPoint(
            x=center.x + radius_x * cos(2.0 * pi * index / segments),
            y=center.y + radius_y * sin(2.0 * pi * index / segments),
        )
        for index in range(segments)
    ]
    if any(point.x < 0.0 or point.x > 1.0 or point.y < 0.0 or point.y > 1.0 for point in points):
        raise ValueError("ellipse extends outside normalized canvas bounds")
    return [*points, points[0]]


def bezier_curve(
    control_points: list[NormalizedPoint],
    *,
    samples: int = 16,
) -> list[NormalizedPoint]:
    """Sample one cubic Bezier segment defined by four normalized control points."""
    if len(control_points) != 4:
        raise ValueError("a cubic Bezier curve requires exactly four control points")
    if not 2 <= samples <= 256:
        raise ValueError("samples must be between 2 and 256")
    p0, p1, p2, p3 = control_points
    result: list[NormalizedPoint] = []
    for index in range(samples + 1):
        t = index / samples
        one_minus_t = 1.0 - t
        x = (
            one_minus_t ** 3 * p0.x
            + 3 * one_minus_t ** 2 * t * p1.x
            + 3 * one_minus_t * t ** 2 * p2.x
            + t ** 3 * p3.x
        )
        y = (
            one_minus_t ** 3 * p0.y
            + 3 * one_minus_t ** 2 * t * p1.y
            + 3 * one_minus_t * t ** 2 * p2.y
            + t ** 3 * p3.y
        )
        result.append(NormalizedPoint(x=x, y=y))
    return result


def polygon_points(vertices: list[NormalizedPoint], *, closed: bool = True) -> list[NormalizedPoint]:
    """Return polygon vertices, optionally repeating the first point to close the path."""
    if len(vertices) < 3:
        raise ValueError("a polygon requires at least three vertices")
    return [*vertices, vertices[0]] if closed and vertices[-1] != vertices[0] else list(vertices)
