import pytest
from PIL import Image

from qwencoder_cua.agent import TaskDecision, TaskPlan, TaskPolicy, TaskRunner, TaskStep
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


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
