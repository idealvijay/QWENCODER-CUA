from __future__ import annotations

import os
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol
from uuid import uuid4

from qwencoder_cua.agent.plan import (
    TaskDecision, TaskPlan, TaskRunResult, TaskStep, TaskStepResult,
)
from qwencoder_cua.agent.policy import TaskPolicy
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.execution.verifier import verify_observation
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.agent.coordinates import planner_image_dimensions
from qwencoder_cua.perception import TargetDetector


class TaskPlanner(Protocol):
    """Planner adapter. It must return one next action or an explicit done decision."""

    def plan_next(self, goal: str, observation: Observation,
                  history: list[TaskStepResult]) -> TaskDecision: ...


ApprovalCallback = Callable[[TaskStep, int], bool]


class TaskRunner:
    """Bounded observe → plan → act → verify loop.

    Planners emit structured data only. Execution is restricted to the action
    allow-list; shell commands, Python code, and arbitrary tool calls are not
    part of the plan schema.
    """

    def __init__(self, computer, policy: TaskPolicy | None = None, target_detector=None):
        self.computer = computer
        self.policy = policy or TaskPolicy()
        self.target_detector = target_detector or TargetDetector()

    def run(self, goal: str, planner: TaskPlanner,
            approve: ApprovalCallback | None = None) -> TaskRunResult:
        """Ask the planner for one action at a time, re-observing after every verified step."""
        if not goal.strip():
            raise ValueError("goal must not be empty")
        self._require_connected()
        started = datetime.now(timezone.utc)
        run_id = uuid4().hex
        clock_start = time.monotonic()
        history: list[TaskStepResult] = []
        no_change_click_replans = 0
        max_no_change_click_replans = 1

        for index in range(1, self.policy.max_steps + 2):
            remaining = self.policy.max_runtime_seconds - (time.monotonic() - clock_start)
            if remaining <= 0:
                return self._run_result(run_id, goal, False, "timed_out", history,
                                        "Task exceeded runtime limit.", started)
            fd, screenshot_path = tempfile.mkstemp(prefix="qwencoder-plan-", suffix=".png")
            os.close(fd)
            try:
                observation = self.computer.observe(screenshot_path=screenshot_path)
                decision = planner.plan_next(goal, observation, list(history))
                if not isinstance(decision, TaskDecision):
                    decision = TaskDecision.model_validate(decision)
            finally:
                Path(screenshot_path).unlink(missing_ok=True)

            if decision.done:
                return self._run_result(
                    run_id, goal, decision.success,
                    "completed" if decision.success else "failed", history,
                    decision.reason or ("Planner marked the task complete." if decision.success
                                        else "Planner could not complete the task."), started,
                )
            if index > self.policy.max_steps:
                return self._run_result(
                    run_id, goal, False, "timed_out", history,
                    f"Planner requested more actions than the {self.policy.max_steps}-step limit.", started,
                )
            if decision.step is None:
                return self._run_result(run_id, goal, False, "failed", history,
                                        "Planner returned no action.", started)

            # One-step execution inherits the remaining global time budget.
            remaining = self.policy.max_runtime_seconds - (time.monotonic() - clock_start)
            if remaining <= 0:
                return self._run_result(run_id, goal, False, "timed_out", history,
                                        "Task exceeded runtime limit.", started)
            step_policy = replace(self.policy, max_steps=1, max_runtime_seconds=max(0.1, remaining))
            step_runner = TaskRunner(
                self.computer, step_policy, target_detector=self.target_detector
            )
            step_plan = TaskPlan(goal=goal, steps=[decision.step])
            wrapped_approval = None
            if approve is not None:
                wrapped_approval = lambda step, _local_index: approve(step, index)
            step_result = step_runner.execute(
                step_plan, approve=wrapped_approval, coordinate_space="planner_image"
            )
            if not step_result.success:
                if (
                    no_change_click_replans < max_no_change_click_replans
                    and self._can_replan_after_no_change(goal, decision.step, step_result)
                ):
                    no_change_click_replans += 1
                    # Preserve the failed attempt in planner history and include its
                    # planner-image point so the model can inspect the fresh screenshot
                    # without blindly repeating the same click.
                    failed = step_result.steps[-1]
                    attempted = (
                        f"planner-image point ({decision.step.x}, {decision.step.y})"
                        if decision.step.action == "click"
                        else f"named target {decision.step.target_id!r}"
                    )
                    failed = failed.model_copy(update={
                        "message": (
                            f"{failed.message} Last attempted {attempted}. "
                            "This click had no detected visual effect; re-inspect the screen "
                            "and do not repeat the same target or point."
                        )
                    })
                    history.extend([*step_result.steps[:-1], failed])
                    continue
                history.extend(step_result.steps)
                return self._run_result(
                    run_id, goal, False, step_result.status, history,
                    step_result.message, started,
                )
            history.extend(step_result.steps)

        return self._run_result(
            run_id, goal, False, "timed_out", history,
            f"Planner did not finish within the {self.policy.max_steps}-step limit.", started,
        )

    @staticmethod
    def _can_replan_after_no_change(
        goal: str, step: TaskStep, result: TaskRunResult
    ) -> bool:
        """Allow one fresh planner observation after an ineffective Paint setup click."""
        task = goal.casefold()
        is_paint_drawing = (
            "paint" in task
            and any(word in task for word in ("draw", "circle", "ellipse", "shape", "sketch"))
        )
        if not is_paint_drawing or step.action not in {"click", "click_target"}:
            return False
        if "screen_changed" not in step.expected or result.status != "failed":
            return False
        if len(result.steps) != 1:
            return False
        attempt = result.steps[0]
        return (
            attempt.dispatched
            and not attempt.verified
            and "Changed pixels: 0.0%" in attempt.message
        )

    def execute(
        self,
        plan: TaskPlan,
        approve: ApprovalCallback | None = None,
        coordinate_space: Literal["desktop", "planner_image"] = "desktop",
    ) -> TaskRunResult:
        """Execute a fixed plan.

        Fixed plans default to native desktop pixels. The closed-loop vision planner
        explicitly selects planner_image coordinates, which are scaled before dispatch.
        """
        if coordinate_space not in {"desktop", "planner_image"}:
            raise ValueError("coordinate_space must be 'desktop' or 'planner_image'.")
        self._require_connected()
        if not isinstance(plan, TaskPlan):
            plan = TaskPlan.model_validate(plan)
        started = datetime.now(timezone.utc)
        clock_start = time.monotonic()
        results: list[TaskStepResult] = []

        if len(plan.steps) > self.policy.max_steps:
            return self._result(plan, False, "failed", results,
                                "Plan exceeds the configured step limit.", started)

        for index, step in enumerate(plan.steps, start=1):
            elapsed = time.monotonic() - clock_start
            if elapsed >= self.policy.max_runtime_seconds:
                return self._result(plan, False, "timed_out", results,
                                    "Task exceeded runtime limit.", started)
            if step.action not in self.policy.allowed_actions:
                return self._result(plan, False, "failed", results,
                                    f"Action {step.action!r} is not allowed.", started)
            if step.action == "type_text" and len(step.text or "") > self.policy.max_text_chars:
                return self._result(plan, False, "failed", results,
                                    "Text exceeds configured length limit.", started)
            if step.action == "draw_path":
                if len(step.points or []) > self.policy.max_path_points:
                    return self._result(plan, False, "failed", results,
                                        "Drawing path exceeds the configured waypoint limit.", started)
                if step.duration_seconds > self.policy.max_draw_duration_seconds:
                    return self._result(plan, False, "failed", results,
                                        "Drawing duration exceeds the configured limit.", started)
            if step.action == "drag" and step.duration_seconds > self.policy.max_draw_duration_seconds:
                return self._result(plan, False, "failed", results,
                                    "Drag duration exceeds the configured limit.", started)

            if step.approval_required and not bool(approve and approve(step, index)):
                return self._result(
                    plan, False, "approval_required", results,
                    f"Step {index} requires user approval and was not approved.", started,
                )

            before_fd, before_path_str = tempfile.mkstemp(prefix="qwencoder-before-", suffix=".png")
            os.close(before_fd)
            after_fd, after_path_str = tempfile.mkstemp(prefix="qwencoder-after-", suffix=".png")
            os.close(after_fd)
            before_path, after_path = Path(before_path_str), Path(after_path_str)
            try:
                before = self.computer.observe(screenshot_path=before_path)
                dispatch_step = step
                dispatch_coordinate_space = coordinate_space
                try:
                    if step.action == "click_target":
                        dispatch_step = self._resolve_target_click(step, before)
                        dispatch_coordinate_space = "desktop"
                except Exception as exc:
                    results.append(TaskStepResult(
                        step_id=step.step_id, action=step.action, dispatched=False,
                        verified=False, message=f"Target resolution failed: {exc}",
                        before_observation_id=before.observation_id,
                    ))
                    if plan.stop_on_failure:
                        return self._result(plan, False, "failed", results,
                                            "Target resolution failed.", started)
                    continue
                bounds_error = self._validate_pointer_bounds(
                    dispatch_step, before, dispatch_coordinate_space
                )
                if bounds_error:
                    results.append(TaskStepResult(
                        step_id=step.step_id, action=step.action, dispatched=False,
                        verified=False, message=bounds_error,
                        before_observation_id=before.observation_id,
                    ))
                    if plan.stop_on_failure:
                        return self._result(plan, False, "failed", results, bounds_error, started)
                    continue
                try:
                    if dispatch_coordinate_space == "planner_image":
                        dispatch_step = self._to_desktop_coordinates(dispatch_step, before)
                    self._dispatch(dispatch_step)
                except Exception as exc:
                    results.append(TaskStepResult(
                        step_id=step.step_id, action=step.action, dispatched=False,
                        verified=False, message=f"Action dispatch failed: {exc}",
                        before_observation_id=before.observation_id,
                    ))
                    if plan.stop_on_failure:
                        return self._result(plan, False, "failed", results,
                                            "Action dispatch failed.", started)
                    continue

                deadline = min(
                    time.monotonic() + step.timeout_seconds,
                    clock_start + self.policy.max_runtime_seconds,
                )
                after = None
                verified, message = False, "Verification did not run."
                while True:
                    after = self.computer.observe(screenshot_path=after_path)
                    try:
                        verified, message = verify_observation(
                            after, step.expected, previous_screenshot_path=str(before_path)
                        )
                    except Exception as exc:
                        verified, message = False, f"Invalid postcondition: {exc}"
                    if verified or time.monotonic() >= deadline:
                        break
                    time.sleep(self.policy.verification_poll_interval)

                results.append(TaskStepResult(
                    step_id=step.step_id, action=step.action, dispatched=True,
                    verified=verified, message=message,
                    before_observation_id=before.observation_id,
                    after_observation_id=after.observation_id if after else None,
                ))
                if not verified and plan.stop_on_failure:
                    return self._result(
                        plan, False, "failed", results,
                        f"Step {index} could not verify its postcondition.", started,
                    )
            finally:
                before_path.unlink(missing_ok=True)
                after_path.unlink(missing_ok=True)

        all_verified = len(results) == len(plan.steps) and all(
            item.dispatched and item.verified for item in results
        )
        return self._result(
            plan, all_verified, "completed" if all_verified else "failed", results,
            "All steps completed and verified." if all_verified
            else "One or more steps were not verified.", started,
        )

    def _resolve_target_click(self, step: TaskStep, observation: Observation) -> TaskStep:
        """Resolve a named target against the fresh pre-dispatch screenshot."""
        registry = self.target_detector.detect(observation)
        target = registry.resolve(
            step.target_id,
            observation_id=observation.observation_id,
        )
        center = target.center
        return TaskStep(
            step_id=step.step_id,
            action="click",
            x=center.x,
            y=center.y,
            button=step.button,
            expected=step.expected,
            approval_required=step.approval_required,
            timeout_seconds=step.timeout_seconds,
        )

    def _dispatch(self, step: TaskStep):
        if step.action == "click":
            self.computer.click(step.x, step.y)
        elif step.action == "type_text":
            self.computer.type_text(step.text)
        elif step.action == "press_key":
            self.computer.press_key(step.key)
        elif step.action == "scroll":
            self.computer.scroll(step.dx, step.dy)
        elif step.action == "move_mouse":
            self.computer.move(step.x, step.y)
        elif step.action == "drag":
            self.computer.drag(
                step.start_x, step.start_y, step.end_x, step.end_y,
                button=step.button, duration_seconds=step.duration_seconds,
            )
        elif step.action == "draw_path":
            self.computer.draw_path(
                [(point.x, point.y) for point in step.points],
                button=step.button, duration_seconds=step.duration_seconds,
            )
        elif step.action in {"click_element", "focus_element", "set_element_value"}:
            if not self.computer._provider:
                raise CUAError("Semantic action requested but accessibility is unavailable.")
            element = self.computer.find_element(step.selector)
            if step.action == "click_element":
                self.computer.click_element(element.id)
            elif step.action == "focus_element":
                self.computer.focus_element(element.id)
            else:
                self.computer.set_element_value(element.id, step.value)
        else:
            raise CUAError(f"Unsupported action: {step.action}")

    @staticmethod
    def _validate_pointer_bounds(
        step: TaskStep,
        observation: Observation,
        coordinate_space: Literal["desktop", "planner_image"] = "desktop",
    ) -> str | None:
        """Reject pointer/drawing coordinates outside the captured desktop image."""
        if step.action not in {"click", "move_mouse", "drag", "draw_path"}:
            return None
        screenshot = observation.screenshot
        if not screenshot or not screenshot.width or not screenshot.height:
            return "Cannot validate pointer coordinates without screenshot dimensions."
        if coordinate_space == "planner_image":
            width, height = planner_image_dimensions(screenshot.width, screenshot.height)
        else:
            width, height = screenshot.width, screenshot.height
        if step.action in {"click", "move_mouse"}:
            points = [(step.x, step.y)]
        elif step.action == "drag":
            points = [(step.start_x, step.start_y), (step.end_x, step.end_y)]
        else:
            points = [(point.x, point.y) for point in (step.points or [])]
        for x, y in points:
            if x is None or y is None or not (0 <= x < width and 0 <= y < height):
                return (
                    f"Pointer coordinate ({x}, {y}) is outside the captured desktop "
                    f"({width}x{height} {coordinate_space} pixels)."
                )
        return None

    @staticmethod
    def _to_desktop_coordinates(step: TaskStep, observation: Observation) -> TaskStep:
        """Map planner-image pixel coordinates to physical desktop screenshot pixels."""
        screenshot = observation.screenshot
        if not screenshot or not screenshot.width or not screenshot.height:
            return step
        image_width, image_height = planner_image_dimensions(
            screenshot.width, screenshot.height
        )
        scale_x = screenshot.width / image_width
        scale_y = screenshot.height / image_height

        def point(x: int, y: int) -> tuple[int, int]:
            return round(x * scale_x), round(y * scale_y)

        if step.action in {"click", "move_mouse"}:
            x, y = point(step.x, step.y)
            return step.model_copy(update={"x": x, "y": y})
        if step.action == "drag":
            sx, sy = point(step.start_x, step.start_y)
            ex, ey = point(step.end_x, step.end_y)
            return step.model_copy(update={
                "start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey,
            })
        if step.action == "draw_path":
            mapped = []
            for item in step.points or []:
                x, y = point(item.x, item.y)
                mapped.append(item.model_copy(update={"x": x, "y": y}))
            return step.model_copy(update={"points": mapped})
        return step

    def _require_connected(self):
        if not getattr(self.computer, "_connected", False):
            raise RuntimeError("Computer must be connected before running a task.")

    @staticmethod
    def _result(plan, success, status, steps, message, started):
        return TaskRunResult(
            plan_id=plan.plan_id, goal=plan.goal, success=success, status=status,
            steps=steps, message=message, started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _run_result(run_id, goal, success, status, steps, message, started):
        return TaskRunResult(
            plan_id=run_id, goal=goal, success=success, status=status,
            steps=steps, message=message, started_at=started,
            completed_at=datetime.now(timezone.utc),
        )
