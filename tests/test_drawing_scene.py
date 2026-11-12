import pytest

from qwencoder_cua.drawing.geometry import bezier_curve, ellipse_points, polygon_points
from qwencoder_cua.drawing.scene_resolver import (
    CanvasRegion,
    canvas_from_target,
    resolve_scene,
)
from qwencoder_cua.models.geometry import Point, Rect
from qwencoder_cua.models.scene import (
    DrawingStyle,
    NormalizedPoint,
    NormalizedRect,
    SceneObject,
    ScenePlan,
)
from qwencoder_cua.models.target import UITarget


def test_canvas_region_maps_normalized_points_and_rectangles():
    canvas = CanvasRegion(
        target_id="paint.canvas.main",
        observation_id="obs-1",
        bounds=Rect(x=100, y=50, width=800, height=600),
    )

    assert canvas.to_screen(
        NormalizedPoint(x=0.5, y=0.5), observation_id="obs-1"
    ) == Point(x=500, y=350)
    assert canvas.to_screen(
        NormalizedPoint(x=0.0, y=0.0), observation_id="obs-1"
    ) == Point(x=100, y=50)
    assert canvas.rect_to_screen(
        NormalizedRect(x=0.25, y=0.25, width=0.5, height=0.5),
        observation_id="obs-1",
    ) == Rect(x=300, y=200, width=400, height=300)


def test_canvas_mapping_rejects_stale_observation():
    canvas = CanvasRegion(
        target_id="paint.canvas.main",
        observation_id="obs-1",
        bounds=Rect(x=0, y=0, width=100, height=100),
    )
    with pytest.raises(ValueError, match="stale"):
        canvas.to_screen(NormalizedPoint(x=0.5, y=0.5), observation_id="obs-2")


def test_canvas_from_target_requires_canvas_target():
    target = UITarget(
        target_id="paint.shape.ellipse",
        label="Ellipse",
        kind="shape",
        bounds=Rect(x=10, y=10, width=20, height=20),
        observation_id="obs-1",
        source="accessibility",
    )
    with pytest.raises(ValueError, match="not classified as a canvas"):
        canvas_from_target(target)


def test_resolve_scene_orders_objects_and_maps_geometry_to_canvas():
    canvas = CanvasRegion(
        target_id="paint.canvas.main",
        observation_id="obs-1",
        bounds=Rect(x=100, y=50, width=800, height=600),
    )
    scene = ScenePlan(
        title="Simple landscape",
        canvas_target_id="paint.canvas.main",
        objects=[
            SceneObject(
                object_id="tree",
                name="Tree",
                primitive="polygon",
                points=[
                    NormalizedPoint(x=0.5, y=0.2),
                    NormalizedPoint(x=0.4, y=0.6),
                    NormalizedPoint(x=0.6, y=0.6),
                ],
                style=DrawingStyle(fill="#267A3A", stroke="#124820"),
                z_index=2,
                closed=True,
            ),
            SceneObject(
                object_id="sun",
                name="Sun",
                primitive="ellipse",
                bounds=NormalizedRect(x=0.7, y=0.1, width=0.1, height=0.1),
                style=DrawingStyle(fill="#F9D34A", stroke=None),
                z_index=0,
            ),
        ],
    )

    resolved = resolve_scene(scene, canvas, observation_id="obs-1")

    assert [item.object_id for item in resolved.objects] == ["sun", "tree"]
    assert resolved.objects[0].bounds == Rect(x=660, y=110, width=80, height=60)
    assert resolved.objects[1].points == [
        Point(x=500, y=170), Point(x=420, y=410), Point(x=580, y=410)
    ]


def test_resolve_scene_rejects_mismatched_canvas_id():
    scene = ScenePlan(
        title="Test",
        canvas_target_id="other.canvas",
        objects=[
            SceneObject(
                object_id="sun",
                name="Sun",
                primitive="ellipse",
                bounds=NormalizedRect(x=0.2, y=0.2, width=0.1, height=0.1),
            )
        ],
    )
    canvas = CanvasRegion(
        target_id="paint.canvas.main",
        observation_id="obs-1",
        bounds=Rect(x=0, y=0, width=100, height=100),
    )
    with pytest.raises(ValueError, match="not"):
        resolve_scene(scene, canvas, observation_id="obs-1")


def test_ellipse_geometry_is_smooth_closed_and_bounded():
    points = ellipse_points(
        NormalizedPoint(x=0.5, y=0.5), 0.2, 0.15, segments=24
    )
    assert len(points) == 25
    assert points[0] == points[-1]
    assert all(0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0 for point in points)


def test_cubic_bezier_sampling_preserves_endpoints():
    points = bezier_curve(
        [
            NormalizedPoint(x=0.1, y=0.5),
            NormalizedPoint(x=0.2, y=0.1),
            NormalizedPoint(x=0.8, y=0.1),
            NormalizedPoint(x=0.9, y=0.5),
        ],
        samples=20,
    )
    assert len(points) == 21
    assert points[0] == NormalizedPoint(x=0.1, y=0.5)
    assert points[-1] == NormalizedPoint(x=0.9, y=0.5)


def test_polygon_points_can_close_path():
    points = polygon_points([
        NormalizedPoint(x=0.1, y=0.1),
        NormalizedPoint(x=0.9, y=0.1),
        NormalizedPoint(x=0.5, y=0.9),
    ])
    assert len(points) == 4
    assert points[0] == points[-1]


def test_scene_models_reject_out_of_canvas_geometry():
    with pytest.raises(ValueError, match="fit inside"):
        NormalizedRect(x=0.8, y=0.2, width=0.3, height=0.2)
    with pytest.raises(ValueError, match="at least three"):
        SceneObject(
            object_id="triangle",
            name="Broken triangle",
            primitive="polygon",
            points=[
                NormalizedPoint(x=0.1, y=0.1),
                NormalizedPoint(x=0.8, y=0.1),
            ],
        )
