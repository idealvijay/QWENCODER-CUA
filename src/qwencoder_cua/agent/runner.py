from __future__ import annotations

import os
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol
from uuid import uuid4
import re
from math import hypot

from qwencoder_cua.agent.plan import (
    TaskDecision, TaskPlan, TaskRunResult, TaskStep, TaskStepResult,
)
from qwencoder_cua.agent.policy import TaskPolicy
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.core.target_errors import AmbiguousTargetError, TargetNotFoundError
from qwencoder_cua.execution.verifier import verify_observation
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.target import UITarget
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
        stale_target_replans = 0
        max_stale_target_replans = 1

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

            # Target IDs belong to the planner's observation. Resolve the semantic
            # target now and carry its identity into dispatch, rather than expecting
            # an observation-scoped ID to survive a second screenshot capture.
            target_hint = None
            if decision.step.action == "click_target":
                try:
                    target_hint = self._resolve_planned_target_hint(
                        decision.step, observation
                    )
                except (TargetNotFoundError, AmbiguousTargetError) as exc:
                    stale_target_replans += 1
                    failed = TaskStepResult(
                        step_id=decision.step.step_id,
                        action=decision.step.action,
                        dispatched=False,
                        verified=False,
                        message=(
                            f"Planner target validation failed: {exc}. Use only an exact "
                            "target from the current observation's available_targets. "
                            "When an ID is an approximate label, use a coordinate grounded "
                            "in the current screenshot instead."
                        ),
                        before_observation_id=observation.observation_id,
                    )
                    history.append(failed)
                    if stale_target_replans <= max_stale_target_replans:
                        continue
                    return self._run_result(
                        run_id, goal, False, "failed", history,
                        "Planner target was not present or was ambiguous.", started,
                    )

            step_to_execute = decision.step
            if target_hint is not None:
                step_to_execute = self._tune_target_selection_postcondition(
                    decision.step, target_hint
                )

            # One-step execution inherits the remaining global time budget.
            remaining = self.policy.max_runtime_seconds - (time.monotonic() - clock_start)
            if remaining <= 0:
                return self._run_result(run_id, goal, False, "timed_out", history,
                                        "Task exceeded runtime limit.", started)
            step_policy = replace(self.policy, max_steps=1, max_runtime_seconds=max(0.1, remaining))
            step_runner = TaskRunner(
                self.computer, step_policy, target_detector=self.target_detector
            )
            step_plan = TaskPlan(goal=goal, steps=[step_to_execute])
            wrapped_approval = None
            if approve is not None:
                wrapped_approval = lambda step, _local_index: approve(step, index)
            step_result = step_runner.execute(
                step_plan, approve=wrapped_approval, coordinate_space="planner_image",
                target_hint=target_hint,
            )
            if not step_result.success:
                if (
                    no_change_click_replans < max_no_change_click_replans
                    and self._can_replan_after_no_change(
                        goal, decision.step, step_result, observation
                    )
                ):
                    no_change_click_replans += 1
                    # Preserve the failed attempt in planner history and include its
                    # planner-image point or named target so the model can inspect the
                    # fresh screenshot without blindly repeating the same click.
                    failed = step_result.steps[-1]
                    attempted = (
                        f"planner-image point: ({decision.step.x}, {decision.step.y})"
                        if decision.step.action == "click"
                        else f"named target: {decision.step.target_id!r}"
                    )
                    failed = failed.model_copy(update={
                        "message": (
                            f"{failed.message} Last attempted {attempted}. "
                            "This click had no detected visual effect; re-inspect the current "
                            "screenshot and do not repeat the same target or point."
                        )
                    })
                    history.extend([*step_result.steps[:-1], failed])
                    continue

                if (
                    stale_target_replans < max_stale_target_replans
                    and self._can_replan_after_stale_target(
                        goal, decision.step, step_result, observation
                    )
                ):
                    stale_target_replans += 1
                    failed = step_result.steps[-1]
                    failed = failed.model_copy(update={
                        "message": (
                            f"{failed.message} The target ID is not valid for the current "
                            "observation. Re-inspect the NEW screenshot and use only an exact "
                            "target_id listed in the current available_targets. Do not "
                            "reconstruct or reuse the missing ID. If no matching target is "
                            "listed, use a coordinate grounded in the current screenshot."
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
    def _is_paint_drawing_task(goal: str, observation: Observation | None = None) -> bool:
        """Recognize Paint from the selected/active app, not only from the user's wording."""
        task = goal.casefold()
        is_drawing = any(
            word in task for word in ("draw", "circle", "ellipse", "shape", "sketch")
        )
        if not is_drawing:
            return False
        if "paint" in task or "mspaint" in task:
            return True
        if observation is None:
            return False

        windows = (observation.target_window, observation.active_window)
        for window in windows:
            if window is None:
                continue
            identity = f"{window.title} {window.process_name or ''}".casefold()
            if "paint" in identity or "mspaint" in identity:
                return True
        return False

    @staticmethod
    def _can_replan_after_no_change(
        goal: str,
        step: TaskStep,
        result: TaskRunResult,
        observation: Observation | None = None,
    ) -> bool:
        """Allow one fresh observation after an ineffective Paint drawing setup click."""
        if not TaskRunner._is_paint_drawing_task(goal, observation):
            return False
        if step.action not in {"click", "click_target"}:
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

    @staticmethod
    def _can_replan_after_stale_target(
        goal: str,
        step: TaskStep,
        result: TaskRunResult,
        observation: Observation | None = None,
    ) -> bool:
        """Allow one fresh planner pass when a Paint target ID is absent from the new tree."""
        if not TaskRunner._is_paint_drawing_task(goal, observation):
            return False
        if step.action != "click_target" or result.status != "failed":
            return False
        if len(result.steps) != 1:
            return False
        attempt = result.steps[0]
        message = attempt.message.casefold()
        return (
            not attempt.dispatched
            and (
                (
                    "target resolution failed" in message
                    and "not in the current observation" in message
                )
                or "could not re-identify" in message
            )
        )

    def execute(
        self,
        plan: TaskPlan,
        approve: ApprovalCallback | None = None,
        coordinate_space: Literal["desktop", "window", "planner_image"] = "desktop",
        target_hint: UITarget | None = None,
    ) -> TaskRunResult:
        """Execute a fixed plan.

        Fixed plans default to native desktop pixels. The closed-loop vision planner
        explicitly selects planner_image coordinates, which are scaled before dispatch.
        """
        if coordinate_space not in {"desktop", "window", "planner_image"}:
            raise ValueError("coordinate_space must be desktop, window or planner_image.")
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
                        dispatch_step = self._resolve_target_click(
                            step, before, target_hint=target_hint
                        )
                        dispatch_coordinate_space = (
                            "window" if before.screenshot
                            and before.screenshot.coordinate_space == "window"
                            else "desktop"
                        )
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
                    if dispatch_coordinate_space != "desktop":
                        dispatch_step = self._to_desktop_coordinates(
                            dispatch_step, before, dispatch_coordinate_space
                        )
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

    @staticmethod
    def _tune_target_selection_postcondition(
        step: TaskStep, target_hint: UITarget
    ) -> TaskStep:
        """Use a small, quantization-aware threshold for tiny toolbar selection changes.

        Paint shape/tool/color buttons often change only a small highlight. The verifier
        compares 64x64 thumbnails (4096 samples), so 4 changed samples equal 0.0977%:
        visibly rounded to 0.1%, but just below the 0.1% threshold. Lower only the
        planner's standard 0.1% threshold for semantic selection clicks; keep drawing
        strokes, drags, canvas actions and stricter custom thresholds unchanged.
        """
        if target_hint.kind not in {"shape", "tool", "color"}:
            return step
        if step.action != "click_target":
            return step
        config = step.expected.get("screen_changed")
        if not isinstance(config, dict):
            return step
        try:
            threshold = float(config.get("min_fraction", 0.01))
        except (TypeError, ValueError):
            return step
        if abs(threshold - 0.001) > 1e-12:
            return step

        expected = dict(step.expected)
        expected["screen_changed"] = {
            **config,
            "min_fraction": 0.0005,
        }
        return step.model_copy(update={"expected": expected})

    @staticmethod
    def _target_id_alias_tokens(target_id: str) -> set[str]:
        reserved = {
            "desktop", "paint", "photoshop", "tool", "shape", "control",
            "button", "color", "menu", "field", "canvas", "unknown",
        }
        return {
            token for token in re.findall(r"[a-z0-9]+", target_id.casefold())
            if token not in reserved and len(token) > 1
        }

    def _resolve_planned_target_hint(
        self, step: TaskStep, observation: Observation
    ) -> UITarget:
        """Resolve exact planner IDs, with a unique semantic-label fallback for model aliases."""
        registry = self.target_detector.detect(observation)
        try:
            return registry.resolve(
                step.target_id, observation_id=observation.observation_id
            )
        except TargetNotFoundError:
            pass

        tokens = self._target_id_alias_tokens(step.target_id)
        if not tokens:
            raise TargetNotFoundError(
                f"Target {step.target_id!r} is not in the planner observation."
            )
        candidates = []
        for target in registry.all(observation_id=observation.observation_id):
            if not target.visible or not target.enabled or target.confidence < 0.65:
                continue
            searchable = " ".join((
                target.label,
                target.kind,
                str(target.metadata.get("automation_id") or ""),
                str(target.metadata.get("class_name") or ""),
            )).casefold()
            words = set(re.findall(r"[a-z0-9]+", searchable))
            if tokens.intersection(words):
                candidates.append(target)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise AmbiguousTargetError(
                f"Target alias {step.target_id!r} matches {len(candidates)} visible controls."
            )
        raise TargetNotFoundError(
            f"Target {step.target_id!r} is not among the current available targets."
        )

    @staticmethod
    def _same_semantic_target(candidate: UITarget, hint: UITarget) -> bool:
        """Compare stable UI semantics, deliberately ignoring observation-scoped element IDs."""
        if candidate.kind != hint.kind:
            return False
        if " ".join(candidate.label.casefold().split()) != " ".join(
            hint.label.casefold().split()
        ):
            return False
        for key in ("role", "automation_id", "class_name", "parent_name"):
            expected = hint.metadata.get(key)
            actual = candidate.metadata.get(key)
            if expected and actual != expected:
                return False
        return True

    @staticmethod
    def _nearest_semantic_target(
        candidates: list[UITarget], hint: UITarget
    ) -> UITarget:
        if len(candidates) == 1:
            return candidates[0]
        ranked = sorted(
            candidates,
            key=lambda item: hypot(
                item.center.x - hint.center.x, item.center.y - hint.center.y
            ),
        )
        best_distance = hypot(
            ranked[0].center.x - hint.center.x,
            ranked[0].center.y - hint.center.y,
        )
        second_distance = hypot(
            ranked[1].center.x - hint.center.x,
            ranked[1].center.y - hint.center.y,
        )
        width = max(hint.bounds.width, ranked[0].bounds.width)
        height = max(hint.bounds.height, ranked[0].bounds.height)
        max_distance = max(12.0, hypot(width, height) * 0.5)
        if best_distance <= max_distance and second_distance - best_distance >= 4.0:
            return ranked[0]
        raise AmbiguousTargetError(
            f"Fresh observation contains {len(candidates)} possible matches for "
            f"target {hint.label!r}; refusing to guess."
        )

    def _resolve_target_click(
        self,
        step: TaskStep,
        observation: Observation,
        target_hint: UITarget | None = None,
    ) -> TaskStep:
        """Re-identify a planner target in the fresh pre-dispatch observation."""
        registry = self.target_detector.detect(observation)
        if target_hint is None:
            target = registry.resolve(
                step.target_id,
                observation_id=observation.observation_id,
            )
        else:
            candidates = [
                item for item in registry.all(observation_id=observation.observation_id)
                if item.visible and item.enabled and item.confidence >= 0.65
                and self._same_semantic_target(item, target_hint)
            ]
            if not candidates:
                raise TargetNotFoundError(
                    f"Could not re-identify {target_hint.label!r} in the fresh observation."
                )
            target = self._nearest_semantic_target(candidates, target_hint)
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
        coordinate_space: Literal["desktop", "window", "planner_image"] = "desktop",
    ) -> str | None:
        """Reject pointer/drawing coordinates outside the captured desktop image."""
        if step.action not in {"click", "move_mouse", "drag", "draw_path"}:
            return None
        screenshot = observation.screenshot
        if not screenshot or not screenshot.width or not screenshot.height:
            return "Cannot validate pointer coordinates without screenshot dimensions."
        if coordinate_space == "planner_image":
            width, height = planner_image_dimensions(screenshot.width, screenshot.height)
            offset_x = offset_y = 0
        elif coordinate_space == "window":
            width, height = screenshot.width, screenshot.height
            offset_x = offset_y = 0
        else:
            width, height = screenshot.width, screenshot.height
            offset_x = screenshot.origin_x if screenshot.coordinate_space == "window" else 0
            offset_y = screenshot.origin_y if screenshot.coordinate_space == "window" else 0
        if step.action in {"click", "move_mouse"}:
            points = [(step.x, step.y)]
        elif step.action == "drag":
            points = [(step.start_x, step.start_y), (step.end_x, step.end_y)]
        else:
            points = [(point.x, point.y) for point in (step.points or [])]
        for x, y in points:
            if x is None or y is None:
                return "Pointer coordinates must contain both x and y."
            if coordinate_space == "desktop" and screenshot.coordinate_space == "window":
                valid = offset_x <= x < offset_x + width and offset_y <= y < offset_y + height
            else:
                valid = 0 <= x < width and 0 <= y < height
            if not valid:
                return (
                    f"Pointer coordinate ({x}, {y}) is outside the captured "
                    f"{coordinate_space} region ({width}x{height}, origin "
                    f"{offset_x},{offset_y})."
                )
        return None

    @staticmethod
    def _to_desktop_coordinates(
        step: TaskStep,
        observation: Observation,
        coordinate_space: Literal["window", "planner_image"] = "planner_image",
    ) -> TaskStep:
        """Map window/planner-image pixels to global desktop input coordinates."""
        screenshot = observation.screenshot
        if not screenshot or not screenshot.width or not screenshot.height:
            return step
        if coordinate_space == "planner_image":
            image_width, image_height = planner_image_dimensions(
                screenshot.width, screenshot.height
            )
            scale_x = screenshot.width / image_width
            scale_y = screenshot.height / image_height
        elif coordinate_space == "window":
            scale_x = scale_y = 1.0
        else:
            raise ValueError("Only window and planner_image coordinates require conversion.")

        offset_x = screenshot.origin_x if screenshot.coordinate_space == "window" else 0
        offset_y = screenshot.origin_y if screenshot.coordinate_space == "window" else 0

        def point(x: int, y: int) -> tuple[int, int]:
            return round(x * scale_x) + offset_x, round(y * scale_y) + offset_y

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
