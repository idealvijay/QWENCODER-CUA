from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from qwencoder_cua.agent.plan import TaskRunResult, TaskStep, TaskStepResult
from qwencoder_cua.agent.policy import TaskPolicy
from qwencoder_cua.drawing.geometry import ellipse_points, polygon_points
from qwencoder_cua.drawing.scene_resolver import (
    ResolvedScene,
    canvas_from_target,
    resolve_scene,
)
from qwencoder_cua.execution.verifier import verify_observation
from qwencoder_cua.models.geometry import Point
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.scene import (
    DrawingStyle,
    NormalizedPoint,
    SceneObject,
    ScenePlan,
)
from qwencoder_cua.perception import TargetDetector

ApprovalCallback = Callable[[TaskStep, int], bool]
StyleApplier = Callable[[DrawingStyle], None]


class DrawingExecutor:
    """Execute normalized scenes as bounded, verified pointer strokes.

    Every stroke gets a new screenshot, a newly detected canvas target and a fresh
    normalized-to-screen transform. The executor deliberately does not replay screen
    coordinates from an earlier observation.
    """

    def __init__(
        self,
        computer,
        policy: TaskPolicy | None = None,
        target_detector: TargetDetector | None = None,
        *,
        style_applier: StyleApplier | None = None,
        ellipse_segments: int = 32,
        min_change_fraction: float = 0.0001,
    ):
        if not 12 <= ellipse_segments <= 64:
            raise ValueError("ellipse_segments must be between 12 and 64")
        if not 0.0 <= min_change_fraction <= 1.0:
            raise ValueError("min_change_fraction must be between 0 and 1")
        self.computer = computer
        self.policy = policy or TaskPolicy()
        self.target_detector = target_detector or TargetDetector()
        self.style_applier = style_applier
        self.ellipse_segments = ellipse_segments
        self.min_change_fraction = min_change_fraction

    def resolve(self, scene: ScenePlan, observation: Observation) -> ResolvedScene:
        """Resolve a scene against a canvas target in the supplied observation."""
        if not isinstance(scene, ScenePlan):
            scene = ScenePlan.model_validate(scene)
        registry = self.target_detector.detect(observation)
        target = registry.resolve(
            scene.canvas_target_id,
            observation_id=observation.observation_id,
        )
        canvas = canvas_from_target(target)
        return resolve_scene(scene, canvas, observation_id=observation.observation_id)

    def preview(self, scene: ScenePlan) -> ResolvedScene:
        """Capture the current desktop and return screen-space geometry without drawing."""
        self._require_connected()
        observation = self.computer.observe()
        return self.resolve(scene, observation)

    def execute(
        self,
        scene: ScenePlan,
        *,
        approve: ApprovalCallback | None = None,
        approval_required: bool = False,
        button: str = "left",
        duration_seconds: float = 1.0,
        verification_timeout_seconds: float = 4.0,
    ) -> TaskRunResult:
        """Draw a scene with fresh canvas resolution and visual verification per stroke.

        The default style is a one-pixel black outline. For other stroke colours or
        widths, provide a style_applier callback that configures the active application
        before each object. Filled shapes and opacity are not supported by pointer paths.
        """
        self._require_connected()
        if not isinstance(scene, ScenePlan):
            scene = ScenePlan.model_validate(scene)
        if button not in {"left", "middle", "right"}:
            raise ValueError("button must be left, middle or right")
        if not 0.05 <= duration_seconds <= self.policy.max_draw_duration_seconds:
            raise ValueError(
                "duration_seconds must be between 0.05 and the policy draw-duration limit"
            )
        if not 0.05 <= verification_timeout_seconds <= 30.0:
            raise ValueError("verification_timeout_seconds must be between 0.05 and 30")
        if approval_required and approve is None:
            # The task can still be previewed; execution requires an explicit approval callback.
            raise ValueError("approval_required needs an approve callback")

        object_paths = [(item, self._normalized_path(item)) for item in scene.ordered_objects]
        for item in scene.ordered_objects:
            self._validate_style(item.style)

        planned_strokes = sum(
            len(self._chunks(points, self.policy.max_path_points))
            for _, points in object_paths
        )
        if planned_strokes > self.policy.max_steps:
            raise ValueError(
                f"Scene requires {planned_strokes} strokes, exceeding the "
                f"{self.policy.max_steps}-step policy limit."
            )

        started = datetime.now(timezone.utc)
        clock_start = time.monotonic()
        run_id = uuid4().hex
        goal = f"Draw scene: {scene.title}"
        results: list[TaskStepResult] = []
        step_index = 0

        def finish(success: bool, status: str, message: str) -> TaskRunResult:
            return TaskRunResult(
                plan_id=run_id,
                goal=goal,
                success=success,
                status=status,
                steps=results,
                message=message,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )

        for item, normalized_points in object_paths:
            if self.style_applier is not None:
                try:
                    self.style_applier(item.style)
                except Exception as exc:
                    return finish(False, "failed", f"Could not apply style for {item.object_id!r}: {exc}")

            chunks = self._chunks(normalized_points, self.policy.max_path_points)
            for normalized_chunk in chunks:
                step_index += 1
                if time.monotonic() - clock_start >= self.policy.max_runtime_seconds:
                    return finish(False, "timed_out", "Scene drawing exceeded the runtime limit.")

                before_fd, before_name = tempfile.mkstemp(
                    prefix="qwencoder-scene-before-", suffix=".png"
                )
                after_fd, after_name = tempfile.mkstemp(
                    prefix="qwencoder-scene-after-", suffix=".png"
                )
                os.close(before_fd)
                os.close(after_fd)
                before_path, after_path = Path(before_name), Path(after_name)
                before: Observation | None = None
                step: TaskStep | None = None
                try:
                    before = self.computer.observe(screenshot_path=before_path)
                    canvas = self._canvas_from_observation(scene, before)
                    self._validate_canvas_on_screen(canvas.bounds, before)
                    screen_points = [
                        canvas.to_screen(point, observation_id=before.observation_id)
                        for point in normalized_chunk
                    ]
                    self._validate_screen_points(screen_points, canvas.bounds, before)
                    step = TaskStep(
                        action="draw_path",
                        points=screen_points,
                        button=button,
                        duration_seconds=duration_seconds,
                        expected={
                            "screen_changed": {"min_fraction": self.min_change_fraction}
                        },
                        approval_required=approval_required,
                    )
                    if approval_required and not bool(approve and approve(step, step_index)):
                        results.append(TaskStepResult(
                            step_id=step.step_id,
                            action=step.action,
                            dispatched=False,
                            verified=False,
                            message=f"Step {step_index} requires approval and was not approved.",
                            before_observation_id=before.observation_id,
                        ))
                        return finish(
                            False, "approval_required",
                            f"Drawing stopped before stroke {step_index}; approval was not granted.",
                        )

                    self.computer.draw_path(
                        [(point.x, point.y) for point in screen_points],
                        button=button,
                        duration_seconds=duration_seconds,
                    )

                    deadline = min(
                        time.monotonic() + verification_timeout_seconds,
                        clock_start + self.policy.max_runtime_seconds,
                    )
                    after: Observation | None = None
                    verified, message = False, "Verification did not run."
                    while True:
                        after = self.computer.observe(screenshot_path=after_path)
                        verified, message = verify_observation(
                            after,
                            step.expected,
                            previous_screenshot_path=str(before_path),
                        )
                        if verified or time.monotonic() >= deadline:
                            break
                        time.sleep(self.policy.verification_poll_interval)

                    results.append(TaskStepResult(
                        step_id=step.step_id,
                        action=step.action,
                        dispatched=True,
                        verified=verified,
                        message=message,
                        before_observation_id=before.observation_id,
                        after_observation_id=after.observation_id if after else None,
                    ))
                    if not verified:
                        status = (
                            "timed_out"
                            if time.monotonic() - clock_start >= self.policy.max_runtime_seconds
                            else "failed"
                        )
                        return finish(
                            False, status,
                            f"Scene drawing stopped at stroke {step_index}: {message}",
                        )
                except Exception as exc:
                    results.append(TaskStepResult(
                        step_id=step.step_id if step else uuid4().hex[:12],
                        action="draw_path",
                        dispatched=False,
                        verified=False,
                        message=f"Could not draw stroke {step_index}: {exc}",
                        before_observation_id=before.observation_id if before else None,
                    ))
                    return finish(False, "failed", f"Scene drawing stopped at stroke {step_index}.")
                finally:
                    before_path.unlink(missing_ok=True)
                    after_path.unlink(missing_ok=True)

        return finish(True, "completed", f"All {step_index} scene strokes were drawn and visually verified.")

    def _canvas_from_observation(self, scene: ScenePlan, observation: Observation):
        registry = self.target_detector.detect(observation)
        target = registry.resolve(
            scene.canvas_target_id,
            observation_id=observation.observation_id,
        )
        return canvas_from_target(target)

    def _normalized_path(self, item: SceneObject) -> list[NormalizedPoint]:
        if item.primitive == "ellipse":
            bounds = item.bounds
            if bounds is None:
                raise ValueError(f"Ellipse {item.object_id!r} has no bounds.")
            return ellipse_points(
                NormalizedPoint(
                    x=bounds.x + bounds.width / 2.0,
                    y=bounds.y + bounds.height / 2.0,
                ),
                bounds.width / 2.0,
                bounds.height / 2.0,
                segments=self.ellipse_segments,
            )
        if item.primitive == "rectangle":
            bounds = item.bounds
            if bounds is None:
                raise ValueError(f"Rectangle {item.object_id!r} has no bounds.")
            corners = [
                NormalizedPoint(x=bounds.x, y=bounds.y),
                NormalizedPoint(x=bounds.x + bounds.width, y=bounds.y),
                NormalizedPoint(x=bounds.x + bounds.width, y=bounds.y + bounds.height),
                NormalizedPoint(x=bounds.x, y=bounds.y + bounds.height),
            ]
            return polygon_points(corners, closed=True)
        if item.primitive == "polygon":
            return polygon_points(item.points, closed=True)
        if item.primitive == "path" and item.closed and item.points[-1] != item.points[0]:
            return [*item.points, item.points[0]]
        return list(item.points)

    @staticmethod
    def _chunks(points: list[NormalizedPoint], max_points: int) -> list[list[NormalizedPoint]]:
        if len(points) < 2:
            raise ValueError("A drawing stroke requires at least two points.")
        chunks: list[list[NormalizedPoint]] = []
        start = 0
        while start < len(points) - 1:
            chunk = points[start:start + max_points]
            if len(chunk) < 2:
                break
            chunks.append(chunk)
            start += len(chunk) - 1
        return chunks

    def _validate_style(self, style: DrawingStyle) -> None:
        if style.fill is not None:
            raise ValueError("Filled scene objects are not supported by pointer-path drawing.")
        if style.stroke is None:
            raise ValueError("Scene objects must define a visible stroke.")
        if style.stroke_width <= 0:
            raise ValueError("stroke_width must be positive for pointer-path drawing.")
        if style.opacity != 1.0:
            raise ValueError("Opacity is not supported by pointer-path drawing.")
        if self.style_applier is None and (
            style.stroke.casefold() not in {"#000000", "black"} or style.stroke_width != 1.0
        ):
            raise ValueError(
                "Non-default stroke colour/width requires a style_applier callback; "
                "the executor does not silently ignore DrawingStyle."
            )

    @staticmethod
    def _validate_canvas_on_screen(bounds, observation: Observation) -> None:
        screenshot = observation.screenshot
        if screenshot is None or not screenshot.width or not screenshot.height:
            raise ValueError("Cannot draw without current screenshot dimensions.")
        if (
            bounds.x < 0 or bounds.y < 0
            or bounds.x + bounds.width > screenshot.width
            or bounds.y + bounds.height > screenshot.height
        ):
            raise ValueError("Detected canvas bounds extend outside the captured desktop.")

    @staticmethod
    def _validate_screen_points(points: list[Point], bounds, observation: Observation) -> None:
        screenshot = observation.screenshot
        if screenshot is None or not screenshot.width or not screenshot.height:
            raise ValueError("Cannot validate drawing points without screenshot dimensions.")
        right = bounds.x + bounds.width
        bottom = bounds.y + bounds.height
        for point in points:
            if not (
                bounds.x <= point.x < right
                and bounds.y <= point.y < bottom
                and 0 <= point.x < screenshot.width
                and 0 <= point.y < screenshot.height
            ):
                raise ValueError(
                    f"Drawing point ({point.x}, {point.y}) is outside the current canvas."
                )

    def _require_connected(self) -> None:
        if not getattr(self.computer, "_connected", False):
            raise RuntimeError("Computer must be connected before drawing a scene.")
