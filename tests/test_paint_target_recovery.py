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


def test_ineffective_ellipse_selection_marks_mandatory_freehand_fallback():
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
            assert len(history) == 1
            assert history[0].dispatched and not history[0].verified
            assert "Changed pixels: 0.0%" in history[0].message
            assert "ELLIPSE FALLBACK REQUIRED" in history[0].message
            assert "select the Pencil/Pen tool" in history[0].message
            # Do not claim the goal is complete before the freehand artwork exists.
            return TaskDecision(
                done=True,
                success=False,
                reason="The planner must continue with the Pencil fallback.",
            )

    driver = PaintDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=4),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
    assert driver.clicked == [(40, 30, "left")]
    assert len(result.steps) == 1
    assert result.steps[0].dispatched
    assert not result.steps[0].verified


def test_paint_target_alias_resolves_to_unique_current_target():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            assert observation.active_window.process_name == "mspaint.exe"
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    # MiniCPM's role prefix is wrong, but "ellipse" uniquely
                    # identifies the visible Ellipse/Oval target.
                    target_id="paint.tool.ellipse",
                    expected={"active_window_title_contains": "Paint"},
                ))
            assert len(history) == 1
            assert history[0].dispatched and history[0].verified
            return TaskDecision(
                done=True, success=False,
                reason="Ellipse selection worked, but the circle has not been drawn yet.",
            )

    driver = PaintDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=4),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
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
                target_id="paint.control.hexagon",
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



class ChangingEllipseTargetDetector:
    """Simulate UIA element tokens changing between separate observations."""

    def __init__(self, duplicate=False):
        self.calls = 0
        self.duplicate = duplicate

    def detect(self, observation):
        self.calls += 1
        targets = [
            UITarget(
                target_id=f"paint.shape.ellipse.uia-{self.calls}",
                label="Ellipse/Oval",
                kind="shape",
                bounds=Rect(x=20, y=20, width=40, height=20),
                observation_id=observation.observation_id,
                source="accessibility",
                confidence=1.0,
                metadata={
                    "element_id": f"random-token-{self.calls}",
                    "role": "button",
                    "automation_id": "EllipseTool",
                    "class_name": "RibbonButton",
                    "parent_name": "Shapes",
                    "actions": ["focus", "click"],
                },
            )
        ]
        if self.duplicate:
            targets.append(UITarget(
                target_id=f"paint.shape.ellipse-copy.uia-{self.calls}",
                label="Ellipse/Oval",
                kind="shape",
                bounds=Rect(x=300, y=20, width=40, height=20),
                observation_id=observation.observation_id,
                source="accessibility",
                confidence=1.0,
                metadata={
                    "element_id": f"random-token-copy-{self.calls}",
                    "role": "button",
                    "automation_id": "EllipseTool",
                    "class_name": "RibbonButton",
                    "parent_name": "Shapes",
                    "actions": ["focus", "click"],
                },
            ))
        return TargetRegistry(observation.observation_id, targets)


def test_target_alias_is_resolved_and_rebound_across_fresh_observations():
    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                # The model's kind prefix is wrong, but its unique "ellipse" label
                # identifies one current target. The target's generated ID changes
                # on the dispatch observation, simulating new UIA tokens.
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.tool.ellipse",
                    expected={"active_window_title_contains": "Paint"},
                ))
            assert history[-1].dispatched and history[-1].verified
            assert not any(item.action in {"draw_path", "drag"} for item in history)
            return TaskDecision(
                done=True, success=False,
                reason="Ellipse selection worked, but the circle has not been drawn yet.",
            )

    driver = PaintDriver()
    detector = ChangingEllipseTargetDetector()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=3),
            target_detector=detector,
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert result.success
    assert planner.calls == 2
    assert detector.calls == 2
    assert driver.clicked == [(40, 30, "left")]
    assert len(result.steps) == 1
    assert result.steps[0].dispatched and result.steps[0].verified


def test_ambiguous_target_alias_is_rejected_without_clicking():
    driver = PaintDriver()
    detector = ChangingEllipseTargetDetector(duplicate=True)
    with Computer(driver=driver, accessibility=False) as computer:
        runner = TaskRunner(computer, target_detector=detector)
        observation = computer.observe()
        step = TaskStep(
            action="click_target",
            target_id="paint.tool.ellipse",
            expected={"active_window_title_contains": "Paint"},
        )

        from qwencoder_cua.core.target_errors import AmbiguousTargetError
        import pytest

        with pytest.raises(AmbiguousTargetError, match="matches 2 visible controls"):
            runner._resolve_planned_target_hint(step, observation)

    assert driver.clicked == []



def test_tiny_shape_tool_highlight_passes_target_selection_verification():
    class TinyHighlightDriver(PaintDriver):
        def click(self, x, y, button="left"):
            self.clicked.append((x, y, button))
            self.drawing_visible = True

        def screenshot(self, output=None):
            image = Image.new("RGB", (64, 64), "black")
            if self.drawing_visible:
                pixels = image.load()
                # Exactly four samples change in the verifier's 64x64 comparison.
                for point in ((10, 10), (11, 10), (10, 11), (11, 11)):
                    pixels[point] = (255, 255, 255)
            if output:
                image.save(output)
            return image

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_target",
                    target_id="paint.shape.ellipse",
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))
            assert len(history) == 1
            assert history[0].dispatched and history[0].verified
            assert "4/4096 samples" in history[0].message
            return TaskDecision(
                done=True, success=False,
                reason="The toolbar highlight changed, but no circle was drawn.",
            )

    driver = TinyHighlightDriver()
    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=3),
            target_detector=EllipseTargetDetector(),
        ).run("Draw a red circle near the centre of the canvas and verify it.", planner)

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
    assert driver.clicked == [(40, 30, "left")]
    assert len(result.steps) == 1
    assert result.steps[0].dispatched and result.steps[0].verified
    assert "0.1%" in result.steps[0].message
    assert "required 0.1%" in result.steps[0].message


def test_small_target_threshold_tuning_does_not_change_draw_or_strict_checks():
    target = UITarget(
        target_id="paint.shape.ellipse",
        label="Ellipse",
        kind="shape",
        bounds=Rect(x=20, y=20, width=40, height=20),
        observation_id="observation",
        source="accessibility",
    )
    selection_step = TaskStep(
        action="click_target",
        target_id="paint.shape.ellipse",
        expected={"screen_changed": {"min_fraction": 0.001}},
    )
    tuned = TaskRunner._tune_target_selection_postcondition(selection_step, target)
    assert tuned.expected["screen_changed"]["min_fraction"] == 0.0005

    strict_step = selection_step.model_copy(update={
        "expected": {"screen_changed": {"min_fraction": 0.01}}
    })
    strict = TaskRunner._tune_target_selection_postcondition(strict_step, target)
    assert strict.expected["screen_changed"]["min_fraction"] == 0.01

    color_target = target.model_copy(update={"kind": "canvas"})
    unchanged = TaskRunner._tune_target_selection_postcondition(selection_step, color_target)
    assert unchanged.expected["screen_changed"]["min_fraction"] == 0.001



class FreehandFallbackPaintDriver(PaintDriver):
    def __init__(self):
        super().__init__()
        self.pen_selected = False
        self.mouse_is_down = False
        self.stroke_points = []

    def click(self, x, y, button="left"):
        self.clicked.append((x, y, button))
        if (x, y) == (5, 5):
            self.pen_selected = True

    def mouse_down(self, x, y, button="left"):
        self.mouse_is_down = True
        self.stroke_points = [(x, y)]

    def move(self, x, y):
        if self.mouse_is_down:
            self.stroke_points.append((x, y))

    def mouse_up(self, button="left"):
        self.mouse_is_down = False
        if self.stroke_points:
            self.stroke_points.append(self.stroke_points[0])

    def draw_path(self, points, button="left", duration_seconds=1.0):
        self.mouse_down(*points[0], button=button)
        try:
            for point in points[1:]:
                self.move(*point)
        finally:
            self.mouse_up(button=button)

    def screenshot(self, output=None):
        image = Image.new("RGB", (100, 80), "black")
        draw = ImageDraw.Draw(image)
        if self.pen_selected:
            # Visible toolbar highlight showing the Pencil tool was selected.
            draw.rectangle((2, 2, 9, 9), fill=(255, 255, 255))
        if len(self.stroke_points) >= 2:
            draw.line(self.stroke_points, fill=(255, 0, 0), width=2)
        if output:
            image.save(output)
        return image


def test_paint_ellipse_failure_falls_back_to_pen_and_verifies_red_circle():
    from qwencoder_cua.models.selector import ElementSelector
    from qwencoder_cua.models.geometry import Point

    driver = FreehandFallbackPaintDriver()

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            if self.calls == 1:
                return TaskDecision(step=TaskStep(
                    action="click_element",
                    selector=ElementSelector(role="button", name="Ellipse"),
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))

            if self.calls == 2:
                assert len(history) == 1
                assert not history[0].dispatched
                assert "ELLIPSE FALLBACK REQUIRED" in history[0].message
                assert "Do not try Ellipse/Oval again" in history[0].message
                # The planner now chooses the visible Pencil/Pen tool using the
                # screenshot rather than retrying the failed Ellipse selector.
                return TaskDecision(step=TaskStep(
                    action="click",
                    x=5,
                    y=5,
                    expected={"screen_changed": {"min_fraction": 0.0005}},
                ))

            if self.calls == 3:
                assert len(history) == 2
                assert history[1].action == "click"
                assert history[1].dispatched and history[1].verified
                assert driver.pen_selected
                # A smooth closed loop in planner-image coordinates, centred on
                # the 100x80 drawable canvas.
                points = [
                    Point(x=65, y=40),
                    Point(x=61, y=49),
                    Point(x=54, y=55),
                    Point(x=45, y=55),
                    Point(x=38, y=49),
                    Point(x=35, y=40),
                    Point(x=38, y=31),
                    Point(x=45, y=25),
                    Point(x=54, y=25),
                    Point(x=61, y=31),
                    Point(x=65, y=40),
                ]
                return TaskDecision(step=TaskStep(
                    action="draw_path",
                    points=points,
                    duration_seconds=0.4,
                    expected={"screen_changed": {"min_fraction": 0.001}},
                ))

            assert len(history) == 3
            assert history[2].action == "draw_path"
            assert history[2].dispatched and history[2].verified
            # Verify that the new observation contains red pixels on the canvas,
            # rather than accepting the toolbar highlight as task completion.
            with Image.open(observation.screenshot.path) as screenshot:
                red_pixels = sum(
                    1 for pixel in screenshot.convert("RGB").getdata()
                    if pixel[0] > 180 and pixel[1] < 80 and pixel[2] < 80
                )
            assert red_pixels > 0
            return TaskDecision(
                done=True,
                success=True,
                reason="A red freehand circle is visible on the Paint canvas.",
            )

    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer,
            TaskPolicy(max_steps=6),
        ).run(
            "Draw a red circle near the centre of the canvas and verify it.",
            planner,
        )

    assert result.success
    assert result.status == "completed"
    assert planner.calls == 4
    assert result.steps[0].action == "click_element"
    assert not result.steps[0].dispatched
    assert result.steps[1].action == "click"
    assert result.steps[1].dispatched and result.steps[1].verified
    assert result.steps[2].action == "draw_path"
    assert result.steps[2].dispatched and result.steps[2].verified
    assert driver.clicked == [(5, 5, "left")]
    assert len(driver.stroke_points) >= 10


def test_paint_ellipse_failure_fallback_is_only_used_once():
    driver = FreehandFallbackPaintDriver()

    class Planner:
        def __init__(self):
            self.calls = 0

        def plan_next(self, goal, observation, history):
            self.calls += 1
            return TaskDecision(step=TaskStep(
                action="click_element",
                selector={"role": "button", "name": "Ellipse"},
                expected={"screen_changed": {"min_fraction": 0.001}},
            ))

    with Computer(driver=driver, accessibility=False) as computer:
        planner = Planner()
        result = TaskRunner(
            computer, TaskPolicy(max_steps=6)
        ).run(
            "Draw a red circle near the centre of the canvas and verify it.",
            planner,
        )

    assert not result.success
    assert result.status == "failed"
    assert planner.calls == 2
    assert len(result.steps) == 2
    assert all(not step.dispatched for step in result.steps)
    assert driver.clicked == []
