from __future__ import annotations

import json

import pytest
from PIL import Image

from qwencoder_cua.agent import TaskPlan, TaskPolicy, TaskRunner, TaskStep
from qwencoder_cua.agent.coordinates import planner_image_dimensions
from qwencoder_cua.agent.ollama import SYSTEM_PROMPT, OllamaTaskPlanner
from qwencoder_cua.core.driver import BaseDriver
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.core.exceptions import UnsupportedOperationError
from qwencoder_cua.creative import circle_path, rectangle_path
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.geometry import Point
from qwencoder_cua.models.window import WindowInfo
from qwencoder_cua.models.observation import Observation, ScreenshotRef
from qwencoder_cua.drivers.linux.wayland.backend import WaylandPortalDriver


class RecordingDriver(BaseDriver):
    name = "recording"

    def __init__(self, fail_move: bool = False):
        self.events = []
        self.fail_move = fail_move
        self.connected = False

    @property
    def capabilities(self):
        return DriverCapabilities(screenshot=True, mouse_input=True)

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def screenshot(self, output=None):
        image = Image.new("RGB", (100, 80), "white")
        if output:
            image.save(output)
        return image

    def get_windows(self):
        return [WindowInfo(id="1", title="Paint", is_active=True)]

    def get_active_window(self):
        return self.get_windows()[0]

    def focus_window(self, window_id):
        pass

    def click(self, x, y, button="left"):
        self.events.append(("click", x, y, button))

    def move(self, x, y):
        if self.fail_move:
            raise RuntimeError("simulated pointer failure")
        self.events.append(("move", x, y))

    def mouse_down(self, x, y, button="left"):
        self.events.append(("down", x, y, button))

    def mouse_up(self, button="left"):
        self.events.append(("up", button))

    def scroll(self, dx=0, dy=0):
        pass

    def type_text(self, text):
        pass

    def press_key(self, key):
        pass


def test_draw_path_interpolates_and_releases_button(monkeypatch):
    monkeypatch.setattr("qwencoder_cua.core.driver.sleep", lambda _seconds: None)
    driver = RecordingDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        computer.draw_path([(10, 10), (28, 10)], duration_seconds=0.05)

    assert driver.events[0] == ("down", 10, 10, "left")
    assert driver.events[-1] == ("up", "left")
    moves = [event for event in driver.events if event[0] == "move"]
    assert len(moves) >= 3
    assert moves[-1] == ("move", 28, 10)


def test_draw_path_releases_button_when_move_fails(monkeypatch):
    monkeypatch.setattr("qwencoder_cua.core.driver.sleep", lambda _seconds: None)
    driver = RecordingDriver(fail_move=True)
    with Computer(driver=driver, accessibility=False) as computer:
        with pytest.raises(RuntimeError, match="simulated pointer failure"):
            computer.draw_path([(10, 10), (28, 10)], duration_seconds=0.05)

    assert driver.events[0] == ("down", 10, 10, "left")
    assert driver.events[-1] == ("up", "left")


def test_drag_uses_atomic_draw_path(monkeypatch):
    monkeypatch.setattr("qwencoder_cua.core.driver.sleep", lambda _seconds: None)
    driver = RecordingDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        computer.drag(5, 5, 30, 30, duration_seconds=0.05)
    assert driver.events[0] == ("down", 5, 5, "left")
    assert driver.events[-1] == ("up", "left")


def test_draw_path_validates_waypoints_and_duration(monkeypatch):
    monkeypatch.setattr("qwencoder_cua.core.driver.sleep", lambda _seconds: None)
    driver = RecordingDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        with pytest.raises(ValueError, match="between 2 and 64"):
            computer.draw_path([(1, 1)], duration_seconds=0.1)
        with pytest.raises(ValueError, match="between 0.05 and 10"):
            computer.draw_path([(1, 1), (2, 2)], duration_seconds=11)
    assert driver.events == []


def test_circle_and_rectangle_helpers():
    circle = circle_path(20, 30, 10, segments=16)
    assert len(circle) == 17
    assert circle[0] == circle[-1]
    rectangle = rectangle_path(2, 3, 10, 20)
    assert len(rectangle) == 5
    assert rectangle[0] == rectangle[-1]


def test_shape_helpers_reject_invalid_dimensions():
    with pytest.raises(ValueError):
        circle_path(0, 0, 0)
    with pytest.raises(ValueError):
        rectangle_path(0, 0, 0, 20)


def test_task_step_accepts_bounded_draw_path():
    step = TaskStep(
        action="draw_path",
        points=[Point(x=10, y=10), Point(x=20, y=20)],
        duration_seconds=0.5,
        expected={"screen_changed": {"min_fraction": 0.001}},
    )
    assert step.action == "draw_path"


def test_task_step_rejects_missing_or_oversized_path():
    with pytest.raises(Exception):
        TaskStep(action="draw_path", expected={"screen_changed": {}})
    with pytest.raises(Exception):
        TaskStep(
            action="draw_path",
            points=[Point(x=index, y=index) for index in range(65)],
            expected={"screen_changed": {}},
        )


def test_task_runner_dispatches_draw_path_and_checks_bounds(monkeypatch):
    monkeypatch.setattr("qwencoder_cua.core.driver.sleep", lambda _seconds: None)
    driver = RecordingDriver()
    plan = TaskPlan(
        goal="Draw a stroke",
        steps=[TaskStep(
            action="draw_path",
            points=[Point(x=10, y=10), Point(x=30, y=30)],
            duration_seconds=0.05,
            expected={"active_window_title_contains": "Paint"},
        )],
    )
    with Computer(driver=driver, accessibility=False) as computer:
        result = TaskRunner(computer).execute(plan)
    assert result.success
    assert driver.events[0] == ("down", 10, 10, "left")
    assert driver.events[-1] == ("up", "left")


def test_task_runner_rejects_points_outside_desktop_before_dispatch():
    driver = RecordingDriver()
    plan = TaskPlan(
        goal="Draw outside the desktop",
        steps=[TaskStep(
            action="draw_path",
            points=[Point(x=10, y=10), Point(x=110, y=90)],
            expected={"screen_changed": {"min_fraction": 0.001}},
        )],
    )
    with Computer(driver=driver, accessibility=False) as computer:
        result = TaskRunner(computer).execute(plan)
    assert not result.success
    assert not driver.events
    assert "outside the captured desktop" in result.message


def test_task_policy_bounds_drawing_configuration():
    with pytest.raises(ValueError):
        TaskPolicy(max_path_points=65)
    with pytest.raises(ValueError):
        TaskPolicy(max_draw_duration_seconds=11)



def test_wayland_mouse_down_and_up_use_portal_pointer_events(monkeypatch):
    driver = WaylandPortalDriver()
    driver._pointer_granted = True
    events = []
    monkeypatch.setattr(driver, "_notify", lambda method, *args: events.append((method, *args)))

    driver.mouse_down(12, 15, "left")
    driver.mouse_up("left")

    assert events[0] == ("call_notify_pointer_motion_absolute", driver._node_id, 12.0, 15.0)
    assert events[1] == ("call_notify_pointer_button", 0x110, 1)
    assert events[2] == ("call_notify_pointer_button", 0x110, 0)


def test_wayland_pointer_press_requires_user_consent():
    driver = WaylandPortalDriver()
    with pytest.raises(UnsupportedOperationError, match="did not grant pointer control"):
        driver.mouse_down(10, 10, "left")



def test_task_runner_maps_vision_click_coordinates_to_desktop():
    class LargeDesktopDriver(RecordingDriver):
        def screenshot(self, output=None):
            image = Image.new("RGB", (2000, 1000), "white")
            if output:
                image.save(output)
            return image

    driver = LargeDesktopDriver()
    plan = TaskPlan(
        goal="Click the requested point from the planner screenshot",
        steps=[TaskStep(
            action="click", x=640, y=320,
            expected={"active_window_title_contains": "Paint"},
        )],
    )
    with Computer(driver=driver, accessibility=False) as computer:
        result = TaskRunner(computer).execute(plan, coordinate_space="planner_image")

    assert result.success
    assert driver.events == [("click", 1000, 500, "left")]


def test_fixed_plan_coordinates_remain_native_desktop_pixels():
    class LargeDesktopDriver(RecordingDriver):
        def screenshot(self, output=None):
            image = Image.new("RGB", (2000, 1000), "white")
            if output:
                image.save(output)
            return image

    driver = LargeDesktopDriver()
    plan = TaskPlan(
        goal="Click with native desktop coordinates",
        steps=[TaskStep(
            action="click", x=1500, y=700,
            expected={"active_window_title_contains": "Paint"},
        )],
    )
    with Computer(driver=driver, accessibility=False) as computer:
        result = TaskRunner(computer).execute(plan)

    assert result.success
    assert driver.events == [("click", 1500, 700, "left")]



def test_drawing_prompt_trusts_user_blank_canvas_statement():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "user's statement that the canvas is blank is reliable" in normalized
    assert "specific visible marks inside the canvas itself" in normalized
    assert "strongly prefer the built-in Ellipse/Oval shape" in normalized
    assert "then use one drag for the circle's bounding box" in normalized


def test_planner_context_matches_resized_image_dimensions(monkeypatch, tmp_path):
    screenshot_path = tmp_path / "wide-screen.png"
    Image.new("RGB", (3440, 1440), "white").save(screenshot_path)
    captured = {}

    decision = {"done": True, "success": True, "reason": "Observed", "step": None}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_: False,
            "read": lambda self: json.dumps({
                "message": {"content": json.dumps(decision)}
            }).encode("utf-8"),
        })()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="wide",
        platform="windows",
        screenshot=ScreenshotRef(path=str(screenshot_path), width=3440, height=1440),
    )
    planner.plan_next("Describe the desktop.", observation, [])

    user_context = json.loads(captured["payload"]["messages"][1]["content"])
    assert user_context["desktop_size"] == {"width": 3440, "height": 1440}
    assert user_context["screen_size"] == {"width": 1280, "height": 536}
