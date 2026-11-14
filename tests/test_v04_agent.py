import pytest
from PIL import Image

from qwencoder_cua.agent import TaskDecision, TaskPlan, TaskPolicy, TaskRunner, TaskStep
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.perception.target_registry import TargetRegistry


class FakeDriver:
    name = "fake"
    capabilities = DriverCapabilities(screenshot=True)

    def __init__(self):
        self.typed = []
        self.clicked = []
        self.keys = []

    def connect(self): pass
    def disconnect(self): pass
    def screenshot(self, output=None):
        image = Image.new("RGB", (100, 80), "black")
        if output:
            image.save(output)
        return image
    def get_windows(self):
        return [WindowInfo(id="1", title="Test", is_active=True)]
    def get_active_window(self):
        return self.get_windows()[0]
    def focus_window(self, window_id): pass
    def click(self, x, y, button="left"):
        self.clicked.append((x, y, button))
    def move(self, x, y): pass
    def scroll(self, dx=0, dy=0): pass
    def type_text(self, text):
        self.typed.append(text)
    def press_key(self, key):
        self.keys.append(key)


def test_task_step_requires_postcondition():
    with pytest.raises(Exception):
        TaskStep(action="press_key", key="enter")


def test_runner_executes_and_verifies_bounded_step():
    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        plan = TaskPlan(
            goal="Enter a short query",
            steps=[TaskStep(
                action="type_text", text="hello",
                expected={"active_window_title_contains": "Test"},
            )],
        )
        result = TaskRunner(computer).execute(plan)
    assert result.success
    assert result.steps[0].verified
    assert driver.typed == ["hello"]


def test_runner_requires_approval_before_dispatch():
    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        plan = TaskPlan(
            goal="Type a sensitive value",
            steps=[TaskStep(
                action="type_text", text="secret",
                expected={"active_window_title_contains": "Test"},
                approval_required=True,
            )],
        )
        result = TaskRunner(computer).execute(plan)
    assert result.status == "approval_required"
    assert driver.typed == []


def test_runner_enforces_max_steps():
    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        plan = TaskPlan(
            goal="Too many steps",
            steps=[
                TaskStep(action="press_key", key="enter",
                         expected={"active_window_title_contains": "Test"}),
                TaskStep(action="press_key", key="tab",
                         expected={"active_window_title_contains": "Test"}),
            ],
        )
        result = TaskRunner(computer, TaskPolicy(max_steps=1)).execute(plan)
    assert not result.success
    assert result.status == "failed"
    assert driver.keys == []


def test_closed_loop_planner_observes_between_steps():
    class Planner:
        def __init__(self):
            self.calls = 0
        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                assert observation.screenshot.path
                return TaskDecision(
                    done=False,
                    step=TaskStep(
                        action="type_text", text="step-1",
                        expected={"active_window_title_contains": "Test"},
                    ),
                )
            assert len(history) == 1 and history[0].verified
            return TaskDecision(done=True, reason="Goal reached.")

    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(computer, TaskPolicy(max_steps=3)).run("type a value", planner)
    assert result.success
    assert result.status == "completed"
    assert planner.calls == 2
    assert driver.typed == ["step-1"]


def test_unapproved_sensitive_step_is_not_dispatched_by_iterative_runner():
    class Planner:
        def plan_next(self, goal, observation, history):
            return TaskDecision(
                step=TaskStep(
                    action="type_text", text="post",
                    expected={"active_window_title_contains": "Test"},
                    approval_required=True,
                )
            )

    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        result = TaskRunner(computer).run("send a post", Planner())
    assert result.status == "approval_required"
    assert driver.typed == []



def test_closed_loop_replans_once_after_paint_click_has_no_visual_effect():
    class ReplanningDriver(FakeDriver):
        def __init__(self):
            super().__init__()
            self.visible_state = False

        def screenshot(self, output=None):
            image = Image.new("RGB", (100, 80), "black")
            if self.visible_state:
                image.paste("white", (5, 5, 25, 25))
            if output:
                image.save(output)
            return image

        def click(self, x, y, button="left"):
            super().click(x, y, button)
            if (x, y) == (20, 20):
                self.visible_state = True

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                assert not history
                return TaskDecision(
                    step=TaskStep(
                        action="click", x=10, y=10,
                        expected={"screen_changed": {"min_fraction": 0.001}},
                    )
                )
            if self.calls == 2:
                assert len(history) == 1
                assert history[0].dispatched and not history[0].verified
                assert "Changed pixels: 0.0%" in history[0].message
                assert "planner-image point: (10, 10)" in history[0].message
                return TaskDecision(
                    step=TaskStep(
                        action="click", x=20, y=20,
                        expected={"screen_changed": {"min_fraction": 0.001}},
                    )
                )
            assert len(history) == 2 and history[-1].verified
            return TaskDecision(
                done=True, success=False,
                reason="The UI click changed, but no drawing gesture was performed.",
            )

    driver = ReplanningDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(computer, TaskPolicy(max_steps=4)).run(
            "Draw a red circle in Paint.", planner
        )

    assert result.success
    assert result.status == "completed"
    assert planner.calls == 3
    assert driver.clicked == [(10, 10, "left"), (20, 20, "left")]
    assert len(result.steps) == 2
    assert not result.steps[0].verified
    assert result.steps[1].verified


def test_closed_loop_limits_no_change_paint_click_recovery_to_one_retry():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            return TaskDecision(
                step=TaskStep(
                    action="click",
                    x=10 + self.calls,
                    y=10,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                )
            )

    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(computer, TaskPolicy(max_steps=4)).run(
            "Draw a red circle in Paint.", planner
        )

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
    assert len(result.steps) == 2
    assert all(item.dispatched and not item.verified for item in result.steps)



def test_runner_resolves_named_target_against_fresh_observation():
    class FixedTargetDetector:
        def detect(self, observation):
            return TargetRegistry(observation.observation_id, [
                UITarget(
                    target_id="paint.shape.ellipse",
                    label="Ellipse",
                    kind="shape",
                    bounds=Rect(x=20, y=30, width=40, height=20),
                    observation_id=observation.observation_id,
                    source="accessibility",
                    confidence=1.0,
                )
            ])

    driver = FakeDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        plan = TaskPlan(
            goal="Select the ellipse tool",
            steps=[TaskStep(
                action="click_target",
                target_id="paint.shape.ellipse",
                expected={"active_window_title_contains": "Test"},
            )],
        )
        result = TaskRunner(
            computer, target_detector=FixedTargetDetector()
        ).execute(plan, coordinate_space="planner_image")

    assert result.success
    assert result.steps[0].action == "click_target"
    assert driver.clicked == [(40, 40, "left")]


def test_task_step_requires_non_empty_target_id_for_named_click():
    with pytest.raises(Exception, match="target_id"):
        TaskStep(
            action="click_target",
            expected={"screen_changed": {"min_fraction": 0.001}},
        )
    with pytest.raises(Exception, match="target_id"):
        TaskStep(
            action="click_target",
            target_id=" ",
            expected={"screen_changed": {"min_fraction": 0.001}},
        )



def test_iterative_runner_reobserves_after_ineffective_named_paint_target_click():
    class TrackingTargetDetector:
        def __init__(self):
            self.observation_ids = []

        def detect(self, observation):
            self.observation_ids.append(observation.observation_id)
            return TargetRegistry(observation.observation_id, [
                UITarget(
                    target_id="paint.color.red",
                    label="Red",
                    kind="color",
                    bounds=Rect(x=10, y=10, width=12, height=12),
                    observation_id=observation.observation_id,
                    source="accessibility",
                )
            ])

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.color.red",
                    timeout_seconds=0.05,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))
            assert len(history) == 1
            assert "Last attempted named target: 'paint.color.red'" in history[0].message
            return TaskDecision(
                done=True,
                success=False,
                reason="The refreshed screen did not confirm the palette selection.",
            )

    driver = FakeDriver()
    detector = TrackingTargetDetector()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer, TaskPolicy(max_steps=4), target_detector=detector
        ).run("Draw a red circle in Paint.", planner)

    assert not result.success
    assert planner.calls == 2
    assert len(driver.clicked) == 1
    assert len(detector.observation_ids) == 2
    assert detector.observation_ids[1] == result.steps[0].before_observation_id
    assert detector.observation_ids[0] != detector.observation_ids[1]
