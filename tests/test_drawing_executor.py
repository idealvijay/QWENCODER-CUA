from __future__ import annotations

from PIL import Image, ImageDraw
import pytest

from qwencoder_cua.agent.policy import TaskPolicy
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.drawing.executor import DrawingExecutor
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.scene import (
    DrawingStyle,
    NormalizedPoint,
    NormalizedRect,
    SceneObject,
    ScenePlan,
)
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.models.window import WindowInfo
from qwencoder_cua.perception.target_registry import TargetRegistry


class FakeDrawingDriver:
    name = "fake"

    def __init__(self):
        self.paths = []
        self.draw_count = 0

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_windows(self):
        return [WindowInfo(id="1", title="Test Paint", is_active=True)]

    def get_active_window(self):
        return self.get_windows()[0]

    def screenshot(self, output=None):
        image = Image.new("RGB", (220, 140), "black")
        draw = ImageDraw.Draw(image)
        for index in range(self.draw_count):
            x = 2 + (index % 12) * 16
            y = 2 + (index // 12) * 16
            draw.rectangle((x, y, x + 8, y + 8), fill="white")
        if output:
            image.save(output)
        return image

    def draw_path(self, points, button="left", duration_seconds=1.0):
        self.paths.append((list(points), button, duration_seconds))
        self.draw_count += 1


class CanvasTargetDetector:
    def __init__(self, bounds=Rect(x=20, y=10, width=180, height=110)):
        self.bounds = bounds
        self.observation_ids = []

    def detect(self, observation):
        self.observation_ids.append(observation.observation_id)
        return TargetRegistry(observation.observation_id, [
            UITarget(
                target_id="paint.canvas.main",
                label="Canvas",
                kind="canvas",
                bounds=self.bounds,
                observation_id=observation.observation_id,
                source="manual",
            )
        ])


def _scene(item: SceneObject) -> ScenePlan:
    return ScenePlan(
        title="Executor test",
        canvas_target_id="paint.canvas.main",
        objects=[item],
    )


def test_executor_draws_ellipse_in_canvas_relative_coordinates():
    driver = FakeDrawingDriver()
    detector = CanvasTargetDetector()
    scene = _scene(SceneObject(
        object_id="circle",
        name="Circle",
        primitive="ellipse",
        bounds=NormalizedRect(x=0.25, y=0.2, width=0.5, height=0.6),
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(computer, target_detector=detector)
        preview = executor.preview(scene)
        result = executor.execute(scene)

    assert preview.canvas_bounds == Rect(x=20, y=10, width=180, height=110)
    assert result.success
    assert result.status == "completed"
    assert len(driver.paths) == 1
    points = driver.paths[0][0]
    assert len(points) == 33
    assert all(20 <= x < 200 and 10 <= y < 120 for x, y in points)
    assert len(detector.observation_ids) >= 2
    assert len(set(detector.observation_ids)) == len(detector.observation_ids)


def test_executor_splits_long_paths_with_overlapping_chunk_endpoints():
    driver = FakeDrawingDriver()
    points = [
        NormalizedPoint(x=0.1 + 0.8 * index / 129, y=0.5)
        for index in range(130)
    ]
    scene = _scene(SceneObject(
        object_id="long-path",
        name="Long path",
        primitive="path",
        points=points,
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(
            computer,
            target_detector=CanvasTargetDetector(),
            policy=TaskPolicy(max_steps=4, max_path_points=64),
        )
        result = executor.execute(scene)

    assert result.success
    assert [len(path[0]) for path in driver.paths] == [64, 64, 4]
    assert driver.paths[0][0][-1] == driver.paths[1][0][0]
    assert driver.paths[1][0][-1] == driver.paths[2][0][0]


def test_executor_rejects_fill_before_dispatch():
    driver = FakeDrawingDriver()
    scene = _scene(SceneObject(
        object_id="filled",
        name="Filled shape",
        primitive="rectangle",
        bounds=NormalizedRect(x=0.2, y=0.2, width=0.4, height=0.3),
        style=DrawingStyle(fill="#FF0000"),
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(computer, target_detector=CanvasTargetDetector())
        with pytest.raises(ValueError, match="Filled"):
            executor.execute(scene)

    assert driver.paths == []


def test_executor_requires_style_applier_for_non_default_stroke():
    driver = FakeDrawingDriver()
    scene = _scene(SceneObject(
        object_id="red-line",
        name="Red line",
        primitive="line",
        points=[NormalizedPoint(x=0.1, y=0.2), NormalizedPoint(x=0.9, y=0.8)],
        style=DrawingStyle(stroke="#FF0000"),
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(computer, target_detector=CanvasTargetDetector())
        with pytest.raises(ValueError, match="style_applier"):
            executor.execute(scene)

    assert driver.paths == []


def test_executor_uses_callback_to_apply_object_style():
    driver = FakeDrawingDriver()
    applied = []
    scene = _scene(SceneObject(
        object_id="red-line",
        name="Red line",
        primitive="line",
        points=[NormalizedPoint(x=0.1, y=0.2), NormalizedPoint(x=0.9, y=0.8)],
        style=DrawingStyle(stroke="#FF0000", stroke_width=3.0),
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(
            computer,
            target_detector=CanvasTargetDetector(),
            style_applier=applied.append,
        )
        result = executor.execute(scene)

    assert result.success
    assert applied == [scene.objects[0].style]
    assert len(driver.paths) == 1


def test_executor_stops_when_canvas_target_is_not_detected():
    class MissingCanvasDetector:
        def detect(self, observation):
            return TargetRegistry(observation.observation_id, [])

    driver = FakeDrawingDriver()
    scene = _scene(SceneObject(
        object_id="line",
        name="Line",
        primitive="line",
        points=[NormalizedPoint(x=0.1, y=0.1), NormalizedPoint(x=0.9, y=0.9)],
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(computer, target_detector=MissingCanvasDetector())
        result = executor.execute(scene)

    assert not result.success
    assert result.status == "failed"
    assert not driver.paths
    assert result.steps[0].dispatched is False


def test_executor_rejects_scenes_that_exceed_policy_before_any_stroke():
    driver = FakeDrawingDriver()
    points = [
        NormalizedPoint(x=0.1 + 0.8 * index / 69, y=0.5)
        for index in range(70)
    ]
    scene = _scene(SceneObject(
        object_id="long-path",
        name="Long path",
        primitive="path",
        points=points,
    ))

    with Computer(driver=driver, accessibility=False) as computer:
        executor = DrawingExecutor(
            computer,
            target_detector=CanvasTargetDetector(),
            policy=TaskPolicy(max_steps=1, max_path_points=64),
        )
        with pytest.raises(ValueError, match="exceeding"):
            executor.execute(scene)

    assert driver.paths == []
