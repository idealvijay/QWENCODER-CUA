from __future__ import annotations

from PIL import Image, ImageDraw
import pytest

from qwencoder_cua.agent import TaskDecision, TaskPolicy, TaskRunner, TaskStep
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.core.exceptions import UnsupportedOperationError
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.window import WindowInfo, WindowSelector


class FakeWindowDriver:
    name = "fake"
    capabilities = DriverCapabilities(
        screenshot=True, window_enumeration=True, window_focus=True,
        mouse_input=True, keyboard_input=True,
    )

    def __init__(self):
        self.active_id = "10"  # The task was launched from CMD.
        self.paint_id = "42"
        self.focused_ids = []
        self.captured_ids = []
        self.clicked = []
        self.changed = False

    def connect(self):
        pass

    def disconnect(self):
        pass

    def get_windows(self):
        return [
            WindowInfo(
                id="10", title="Command Prompt", process_id=111,
                process_name="cmd.exe", is_active=self.active_id == "10",
            ),
            WindowInfo(
                id=self.paint_id, title="Untitled - Paint", process_id=222,
                process_name="mspaint.exe", bounds=(280, 170, 160, 130),
                is_active=self.active_id == self.paint_id,
            ),
        ]

    def get_active_window(self):
        return next((item for item in self.get_windows() if item.is_active), None)

    def focus_window(self, window_id):
        self.focused_ids.append(window_id)
        self.active_id = window_id

    def screenshot(self, output=None):
        raise AssertionError("Target-window mode must not capture the whole desktop.")

    def capture_window(self, window_id, output=None):
        assert window_id == self.paint_id
        self.captured_ids.append(window_id)
        image = Image.new("RGB", (120, 90), "black")
        if self.changed:
            ImageDraw.Draw(image).rectangle((10, 10, 35, 35), fill="white")
        if output:
            image.save(output)
        return image, (300, 200, 120, 90)

    def click(self, x, y, button="left"):
        self.clicked.append((x, y, button))
        self.changed = True

    def move(self, x, y):
        pass

    def mouse_down(self, x, y, button="left"):
        pass

    def mouse_up(self, button="left"):
        pass

    def scroll(self, dx=0, dy=0):
        pass

    def type_text(self, text):
        pass

    def press_key(self, key):
        pass


def test_window_selector_matches_process_name_case_insensitively():
    selector = WindowSelector(process_name="MSPAINT.EXE")
    window = WindowInfo(
        id="42", title="Untitled - Paint", process_id=222, process_name="mspaint.exe"
    )
    assert selector.matches(window)


def test_computer_captures_target_client_area_not_active_terminal():
    driver = FakeWindowDriver()
    with Computer(
        driver=driver,
        accessibility=False,
        target_window=WindowSelector(process_name="mspaint.exe"),
    ) as computer:
        observation = computer.observe()

    assert observation.active_window.id == "42"
    assert observation.target_window.id == "42"
    assert observation.screenshot.coordinate_space == "window"
    assert observation.screenshot.origin_x == 300
    assert observation.screenshot.origin_y == 200
    assert (observation.screenshot.width, observation.screenshot.height) == (120, 90)
    assert driver.captured_ids == ["42"]


def test_runner_retargets_paint_after_foreground_and_hwnd_change_during_planning():
    driver = FakeWindowDriver()

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                assert observation.target_window.process_name == "mspaint.exe"
                assert observation.active_window.process_name == "mspaint.exe"
                # Simulate CMD becoming foreground while Ollama is thinking.
                # Paint's HWND is recreated, but its process identity remains stable.
                driver.active_id = "10"
                driver.paint_id = "43"
                return TaskDecision(step=TaskStep(
                    action="click",
                    x=15,
                    y=25,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))
            assert history[-1].verified
            assert observation.target_window.id == "43"
            return TaskDecision(done=True, success=True, reason="Target-window task completed.")

    with Computer(
        driver=driver,
        accessibility=False,
        target_window=WindowSelector(process_name="mspaint.exe"),
    ) as computer:
        planner = Planner()
        result = TaskRunner(computer, TaskPolicy(max_steps=3)).run(
            "Click inside the Paint canvas.", planner
        )

    assert result.success
    assert result.status == "completed"
    assert driver.clicked == [(315, 225, "left")]
    assert driver.captured_ids == ["42", "43", "43", "43"]
    assert "43" in driver.focused_ids


def test_computer_localizes_accessibility_bounds_to_window_capture():
    element = UIElement(
        id="e1",
        role="button",
        name="Ellipse",
        bounds=Rect(x=330, y=240, width=40, height=20),
    )
    localized = Computer._localize_elements([element], 300, 200, 120, 90)
    assert localized[0].bounds == Rect(x=30, y=40, width=40, height=20)


def test_target_window_selector_rejects_ambiguous_matches():
    class AmbiguousDriver(FakeWindowDriver):
        def get_windows(self):
            return [
                WindowInfo(
                    id="42", title="Untitled - Paint", process_id=222,
                    process_name="mspaint.exe",
                ),
                WindowInfo(
                    id="43", title="Another Paint Window", process_id=222,
                    process_name="mspaint.exe",
                ),
            ]

    driver = AmbiguousDriver()
    with Computer(
        driver=driver,
        accessibility=False,
        target_window=WindowSelector(process_name="mspaint.exe"),
    ) as computer:
        with pytest.raises(UnsupportedOperationError, match="ambiguous"):
            computer.observe()
