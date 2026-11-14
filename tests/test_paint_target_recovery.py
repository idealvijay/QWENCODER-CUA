from __future__ import annotations

from PIL import Image, ImageDraw

from qwencoder_cua.agent import TaskDecision, TaskPolicy, TaskRunner, TaskStep
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.models.window import WindowInfo
from qwencoder_cua.perception.target_registry import TargetRegistry


class PaintDriver:
    name = "windows"
    capabilities = DriverCapabilities(screenshot=True, mouse_input=True)

    def __init__(self):
        self.clicked = []
        self.drawing_visible = False

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_windows(self):
        return [WindowInfo(
            id="42",
            title="Untitled - Paint",
            process_id=4242,
            process_name="mspaint.exe",
            is_active=True,
        )]

    def get_active_window(self):
        return self.get_windows()[0]

    def focus_window(self, window_id):
        pass

    def screenshot(self, output=None):
        image = Image.new("RGB", (100, 80), "black")
        if self.drawing_visible:
            ImageDraw.Draw(image).rectangle((5, 5, 25, 25), fill="white")
        if output:
            image.save(output)
        return image

    def click(self, x, y, button="left"):
        self.clicked.append((x, y, button))
        # The first attempted tool click is intentionally ineffective.
        if (x, y) == (20, 20):
            self.drawing_visible = True

    def move(self, x, y):
        pass

    def scroll(self, dx=0, dy=0):
        pass

    def type_text(self, text):
        pass

    def press_key(self, key):
        pass


class EllipseTargetDetector:
    def detect(self, observation):
        return TargetRegistry(observation.observation_id, [
            UITarget(
                target_id="paint.shape.ellipse",
                label="Ellipse",
                kind="shape",
                bounds=Rect(x=20, y=20, width=40, height=20),
                observation_id=observation.observation_id,
                source="accessibility",
                confidence=1.0,
            )
        ])


def test_paint_no_change_recovery_uses_window_identity_not_goal_text():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            assert "paint" not in goal.casefold()
            assert observation.active_window.process_name == "mspaint.exe"
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.shape.ellipse",
                    timeout_seconds=0.05,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))
            if self.calls == 2:
                assert len(history) == 1
                assert not history[0].verified
                assert "Changed pixels: 0.0%" in history[0].message
                assert "named target: 'paint.shape.ellipse'" in history[0].message
                return TaskDecision(step=TaskStep(
                    action="click",
                    x=20,
                    y=20,
                    timeout_seconds=0.05,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))
            assert len(history) == 2 and history[-1].verified
            return TaskDecision(done=True, success=True, reason="Circle setup and drawing verified.")

    driver = PaintDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=4),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert result.success
    assert planner.calls == 3
    assert driver.clicked == [(40, 30, "left"), (20, 20, "left")]
    assert len(result.steps) == 2
    assert not result.steps[0].verified
    assert result.steps[1].verified


def test_paint_stale_target_id_gets_one_fresh_observation_retry():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            assert observation.active_window.process_name == "mspaint.exe"
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.control.ellipse",
                    expected={"active_window_title_contains": "Paint"},
                ))
            if self.calls == 2:
                assert len(history) == 1
                assert not history[0].dispatched
                assert "not in the current observation" in history[0].message
                assert "only an exact target_id listed" in history[0].message
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.shape.ellipse",
                    expected={"active_window_title_contains": "Paint"},
                ))
            assert len(history) == 1 and history[0].dispatched
            return TaskDecision(done=True, success=True, reason="The ellipse tool was selected.")

    driver = PaintDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=4),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert result.success
    assert planner.calls == 3
    assert driver.clicked == [(40, 30, "left")]
    assert len(result.steps) == 1
    assert result.steps[0].dispatched
    assert result.steps[0].verified


def test_paint_stale_target_recovery_is_bounded_to_one_retry():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            return TaskDecision(step=TaskStep(
                action="click_target",
                target_id="paint.control.ellipse",
                expected={"active_window_title_contains": "Paint"},
            ))

    driver = PaintDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=5),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
    assert len(result.steps) == 2
    assert all(not item.dispatched for item in result.steps)
    assert driver.clicked == []
