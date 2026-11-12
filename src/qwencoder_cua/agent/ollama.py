from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from qwencoder_cua.agent.plan import TaskDecision, TaskStep
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.agent.coordinates import planner_image_dimensions
from qwencoder_cua.perception import TargetDetector


def _normalize_draw_path_points(step_data: dict[str, Any]) -> None:
    """Normalize common coordinate-pair encodings without changing the point limit."""
    if step_data.get("action") != "draw_path":
        return
    points = step_data.get("points")
    if not isinstance(points, list) or not points:
        return

    def is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    # Some vision models emit [x1, y1, x2, y2, ...] instead of the documented
    # [{"x": x1, "y": y1}, ...] structure. Pair it only when every value is numeric
    # and the list has an unambiguous even length. TaskStep still enforces 2-64 points.
    if all(is_number(value) for value in points):
        if len(points) % 2 == 0:
            step_data["points"] = [
                {"x": points[index], "y": points[index + 1]}
                for index in range(0, len(points), 2)
            ]
        return

    # Also accept the equivalent [[x1, y1], [x2, y2], ...] representation.
    if all(
        isinstance(pair, (list, tuple))
        and len(pair) == 2
        and is_number(pair[0])
        and is_number(pair[1])
        for pair in points
    ):
        step_data["points"] = [
            {"x": pair[0], "y": pair[1]} for pair in points
        ]


SYSTEM_PROMPT = """You are the planning component of QWENCODER CUA, a local desktop automation agent.
Return exactly one JSON object matching:
{"done": boolean, "success": boolean, "reason": string, "step": TaskStep object or null}

The "reason" field is the user-facing completion message. When done=true, step must be null.
Set success=true only when the user's goal is achieved. If blocked, lacking required information,
or unable to complete safely, set done=true and success=false with a clear explanation.

IMPORTANT: Some goals are read-only and require no desktop action. For goals asking you to
describe, identify, inspect, summarize, list, or explain what is currently visible, answer from
the current screenshot and accessibility context. Return done=true, success=true, put the answer
in "reason", and set step=null. Do not invent a click, keypress, or other no-op action just to
complete a read-only request. If the current observation is insufficient, return done=true,
success=false and explain what is missing.

If the user asks about a specific application (for example Paint or Photoshop) and that
application is not the active window, do not invent a click or attempt to switch windows.
Return done=true, success=false, step=null, and explain that the user must bring the target
application to the foreground and run the request again. The allowed action list does not
include window switching.

Otherwise, return exactly one next action and include its expected postcondition.
Allowed actions:
- click: x, y
- type_text: text
- press_key: key (examples: enter, tab, ctrl+c)
- scroll: dx and/or dy
- click_element: selector
- click_target: target_id (an exact ID from available_targets)
- focus_element: selector
- set_element_value: selector and value
- move_mouse: x, y
- drag: start_x, start_y, end_x, end_y, optional button and duration_seconds
- draw_path: points (2-64 objects, each exactly {"x": int, "y": int}), optional button and duration_seconds

Pointer coordinates are measured in the resized image shown to you (the
`screen_size` field), not the full desktop. The runner automatically maps them to desktop
pixels using `desktop_size`. Coordinates returned in actions MUST use `screen_size`
pixels, never `desktop_size` pixels. Before returning a coordinate action, check every
coordinate numerically: `0 <= x < screen_size.width` and `0 <= y < screen_size.height`.
For drag, check both endpoints; for draw_path, check every waypoint. Never return a coordinate
outside those limits, even if the full desktop resolution is larger. If you cannot locate a
safe point inside the image, return done=true, success=false and explain why; do not guess.

Keep every point within `screen_size` and inside the drawable canvas rectangle; never target
the toolbar, ribbon, status bar or title bar as a drawing point.

For drawing tasks, distinguish the canvas from surrounding application chrome. A blank
white/transparent canvas is normal and is not evidence that a tool or colour is missing.
The user's statement that the canvas is blank is reliable unless clear visible artwork
contradicts it. Do not refuse a drawing task because the canvas "does not look empty" unless
you can identify specific visible marks inside the canvas itself. Ignore colour swatches,
tool icons, selection handles and other UI elements when assessing whether the canvas contains
artwork. If the requested tool or colour is not selected, use visible, unambiguous controls to
select it as normal planner steps; do not ask the user to do this when controls are visible.
Normal UI setup is part of the task, not a blocker: selecting a colour, brush, shape or tool and
then using it are actions for you to perform. When the target application is active, never return
a terminal failure saying the user must select a colour/tool/shape or click the canvas if those
controls can be operated with the allowed actions. Instead, return one concrete next UI action.
For a circle in Paint, strongly prefer the built-in Ellipse/Oval shape when it is visibly
available: set no fill and a red outline, then use one drag for the circle's bounding box. Only
use a closed draw_path when no suitable built-in ellipse control is visible. For a freehand circle,
use 12-24 evenly distributed waypoints around one smooth circumference. Every point MUST be a
JSON object with integer x and y fields, for example "points":[{"x":600,"y":300},
{"x":620,"y":280}]. Never return a flat number list or nested coordinate arrays. Do not produce
stair-step, zigzag, rectangular, or repeated-point paths. Do not exceed 64 waypoints. Do not claim
a tool or shape is absent without checking the screenshot and accessible elements.

For a Paint/Photoshop stroke, identify the drawable canvas first. Use draw_path (one atomic
press/move/release) for a freehand path; use drag for a straight drag or a native
ellipse/rectangle tool gesture. A draw_path or drag action must request a screen_changed
postcondition, normally with min_fraction 0.001.

For coordinate-based UI clicks, brush strokes and shape gestures, prefer exactly one
reliable visual postcondition: `"expected": {"screen_changed": {"min_fraction": 0.001}}`.
Do not add guessed semantic assertions such as `element_absent` for colour swatches or tools:
those controls usually remain present after being selected. If the model cannot confirm a
semantic state from accessibility values, use the visual change check and inspect the next
screenshot before planning another action. If completed_steps contains a dispatched click with
verified=false and a message saying "Changed pixels: 0.0%", treat that click as having no detected
visual effect: inspect the current screenshot again, do not assume the click succeeded, and do not
repeat the recorded planner-image point. Decide whether the intended selection is already visible;
otherwise choose a different clearly visible target. The runner permits only one such recovery.

A non-terminal response MUST use this exact structure (no wrapper keys):
{"done": false, "success": true, "reason": "Why this one action is next.", "step": {
  "action": "click", "x": 600, "y": 300,
  "expected": {"screen_changed": {"min_fraction": 0.001}}
}}
For a semantic action, the step still needs an action and expected, for example:
{"action": "click_element", "selector": {"role": "button", "name": "Ellipse"},
 "expected": {"screen_changed": {"min_fraction": 0.001}}}
The step field is mandatory and its action field is mandatory for every non-terminal response.
Use the exact field name "expected"; never use "postcondition". Do not put assertion names such as
"element_absent" directly in the step object. Do not output multiple conditions with duplicate JSON
keys; combine them only if the schema supports them, otherwise verify one condition per step.

Every step MUST include a non-empty expected postcondition. Supported postconditions:
- {"element_absent": {"role": "...", "name": "..."}}
- {"element_present": {"role": "...", "name": "..."}}
- {"element_value": {"selector": {"role": "...", "automation_id": "..."}, "equals": "..."}}
- {"active_window_title_contains": "..."}
- {"screen_changed": {"min_fraction": 0.01}}

When available_targets contains a suitable named target, prefer click_target with its exact
target_id instead of estimating x/y. The runner resolves that ID again against a fresh screenshot
immediately before clicking; never provide coordinates with click_target. If the target is absent
or confidence is insufficient, use a different visible target or a coordinate click grounded in
the screenshot. Target IDs are observation-scoped hints, not durable coordinates.

Prefer accessibility selectors with stable automation_id and parent_name. Use screen coordinates
only when accessibility elements cannot identify the target. Do not invent controls or assume an
action succeeded; inspect the next observation and plan again. Do not use a no-op title check as
a substitute for verifying an actual state change. Mark approval_required=true for consequential
actions such as submitting external messages/forms, deleting data, purchases, or changing security
settings. Never request shell commands, arbitrary Python, file deletion, application launching,
or actions outside this allow-list. Stop with done=true when the goal is achieved, blocked, or
requires information the user has not provided.
"""


class OllamaTaskPlanner:
    """Local Ollama planner using the user's existing OLLAMA_URL / MODEL environment settings.

    Default model is qwen2.5-coder:7b. The model returns one structured step at a time.
    """

    def __init__(self, endpoint: str | None = None, model: str | None = None,
                 timeout_seconds: float = 45.0, num_ctx: int | None = None):
        self.endpoint = (endpoint or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        if not self.endpoint.endswith("/api/chat"):
            self.endpoint = self.endpoint + "/chat" if self.endpoint.endswith("/api") else self.endpoint + "/api/chat"
        self.model = (
            model
            or os.environ.get("QWENCODER_CUA_MODEL")
            or os.environ.get("MODEL")
            or "minicpm-v4.5:q4_0"
        )
        model_hint = self.model.lower()
        self.include_images = any(token in model_hint for token in
                                  ("minicpm-v", "vision", "-vl", "llava"))
        raw_num_ctx = num_ctx if num_ctx is not None else os.environ.get("QWENCODER_CUA_NUM_CTX", "20480")
        try:
            self.num_ctx = int(raw_num_ctx)
        except (TypeError, ValueError) as exc:
            raise ValueError("QWENCODER_CUA_NUM_CTX must be a positive integer.") from exc
        if not 2048 <= self.num_ctx <= 131072:
            raise ValueError("num_ctx must be between 2048 and 131072 tokens.")
        self.timeout_seconds = timeout_seconds

    def plan_next(self, goal: str, observation: Observation, history: list[Any]) -> TaskDecision:
        elements = [
            {
                "role": item.role, "name": item.name, "value": item.value,
                "automation_id": item.automation_id, "class_name": item.class_name,
                "parent_name": item.parent_name, "bounds": item.bounds.model_dump() if item.bounds else None,
                "enabled": item.enabled, "visible": item.visible, "actions": item.actions,
            }
            for item in observation.elements[:160]
        ]
        context = {
            "goal": goal,
            "platform": observation.platform,
            "session_type": observation.session_type,
            "active_window": observation.active_window.model_dump() if observation.active_window else None,
            "accessibility_available": observation.accessibility_available,
            "desktop_size": (
                {"width": observation.screenshot.width, "height": observation.screenshot.height}
                if observation.screenshot else None
            ),
            "screen_size": (
                {"width": planner_image_dimensions(
                    observation.screenshot.width, observation.screenshot.height
                )[0], "height": planner_image_dimensions(
                    observation.screenshot.width, observation.screenshot.height
                )[1]}
                if observation.screenshot else None
            ),
            "accessible_elements": elements,
            "available_targets": TargetDetector().detect(observation).prompt_context(
                observation_id=observation.observation_id
            )[:80],
            "completed_steps": [item.model_dump() for item in history[-12:]],
        }
        message = {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
        images = self._read_observation_image(observation) if self.include_images else []
        if images:
            message["images"] = images
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, message]
        try:
            # Local vision models sometimes return an almost-correct TaskStep but omit
            # required fields or use "postcondition" instead of the schema's "expected".
            # Give the model one bounded repair attempt; never guess the missing action.
            for attempt in range(2):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"num_ctx": self.num_ctx},
                }
                request = urllib.request.Request(
                    self.endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body.get("message", {}).get("content")
                if not isinstance(content, str):
                    raise CUAError("Ollama returned no JSON message content.")
                decision_data = json.loads(content)

                if isinstance(decision_data, dict):
                    # Ignore formatting-only keys, but continue to reject meaningful extras.
                    decision_data = {
                        key: value
                        for key, value in decision_data.items()
                        if not (isinstance(key, str) and not key.strip())
                    }
                    step_data = decision_data.get("step")
                    if isinstance(step_data, dict):
                        _normalize_draw_path_points(step_data)
                        # Accept the common natural-language alias, but do not infer action.
                        if "expected" not in step_data and isinstance(step_data.get("postcondition"), dict):
                            step_data["expected"] = step_data.pop("postcondition")

                        expected = step_data.get("expected")
                        if isinstance(expected, dict) and "screen_changed" in expected:
                            # A visual screenshot-difference check is the reliable oracle for
                            # coordinate-driven UI input. MiniCPM often invents semantic element
                            # assertions for controls that are not exposed by UI Automation or
                            # that remain present after selection. Combining those assertions
                            # with screen_changed makes verification fail even when the visual
                            # interaction clearly changed the screen. For pointer actions, use
                            # the visual assertion alone. Semantic actions may retain supported
                            # semantic postconditions because those are their intended oracle.
                            pointer_actions = {"click", "click_target", "move_mouse", "drag", "draw_path"}
                            if step_data.get("action") in pointer_actions:
                                step_data["expected"] = {
                                    "screen_changed": expected["screen_changed"]
                                }
                            else:
                                supported = {
                                    "active_window_title_contains", "screen_changed",
                                    "element_absent", "element_present", "element_value",
                                }
                                step_data["expected"] = {
                                    key: value for key, value in expected.items()
                                    if key in supported
                                }
                    # A terminal decision must never dispatch any attached action.
                    if decision_data.get("done") is True and decision_data.get("step") is not None:
                        decision_data["step"] = None

                try:
                    decision = TaskDecision.model_validate(decision_data)
                    if self._is_manual_ui_handoff(goal, observation, decision):
                        if attempt == 0:
                            active = observation.active_window
                            active_identity = (
                                f"title={active.title!r}, process={active.process_name!r}"
                                if active else "unknown"
                            )
                            messages = [
                                *messages,
                                {"role": "assistant", "content": content},
                                {
                                    "role": "user",
                                    "content": (
                                        "Your terminal response conflicts with platform window metadata. "
                                        f"The OS foreground-window API reports: {active_identity}. "
                                        "This metadata identifies the foreground window, but it does "
                                        "not prove that its contents are visible in the screenshot. "
                                        "Re-examine the attached screenshot carefully. If Paint is "
                                        "visibly present, continue the drawing task with one concrete "
                                        "allowed action; do not tell the user to switch applications. "
                                        "If the screenshot genuinely shows a different app covering "
                                        "Paint or does not contain Paint, stop safely and report a "
                                        "screenshot/window mismatch; do not send clicks to an unknown "
                                        "surface. For normal setup, you must select visible colours, "
                                        "tools and shapes yourself, one action per response. Do not "
                                        "claim an action has happened until dispatched and verified.\n"
                                        f"Previous terminal response: {decision.reason}"
                                    ),
                                },
                            ]
                            continue
                        return TaskDecision(
                            done=True,
                            success=False,
                            reason=(
                                "The planner could not resolve the screenshot/window mismatch between "
                                "foreground-window metadata and the captured image after one "
                                "correction. No desktop action was dispatched. Verify that Paint "
                                "is visible on the captured desktop and rerun the task. Model response: "
                                f"{decision.reason}"
                            ),
                            step=None,
                        )
                    coordinate_errors = self._coordinate_errors(
                        decision.step, context.get("screen_size")
                    )
                    if coordinate_errors:
                        detail = " ".join(coordinate_errors)
                        if attempt == 0:
                            messages = [
                                *messages,
                                {"role": "assistant", "content": content},
                                {
                                    "role": "user",
                                    "content": (
                                        "Your last action used coordinates outside the image. "
                                        "Do not repeat them. Return a corrected decision using only "
                                        "coordinates inside the exact planner image dimensions below. "
                                        "Coordinates are planner-image pixels, not desktop pixels. "
                                        f"Planner image dimensions: {context.get('screen_size')}. "
                                        "Required bounds: 0 <= x < width and 0 <= y < height for "
                                        "every click/move point, both drag endpoints, and every "
                                        "draw_path waypoint. Re-examine the attached screenshot and "
                                        "choose a point inside the Paint control/canvas. Do not "
                                        "clamp the previous coordinate or invent a location. If no "
                                        "safe point can be identified, return done=true, success=false.\n"
                                        f"Coordinate validation: {detail}"
                                    ),
                                },
                            ]
                            continue
                        raise CUAError(
                            "Ollama returned out-of-range pointer coordinates after one correction "
                            f"attempt. Planner image: {context.get('screen_size')}. {detail}"
                        )
                    return decision
                except ValidationError as exc:
                    if attempt == 0:
                        validation_detail = str(exc)[:1800]
                        previous_response = content[:3000]
                        messages = [
                            *messages,
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": (
                                    "Your previous JSON was rejected by the TaskDecision / TaskStep "
                                    "schema. Correct it and return exactly one complete JSON object. "
                                    "Do not omit required fields and do not invent field names.\n"
                                    "For a non-terminal action, the top-level decision must have "
                                    "\"done\": false and \"step\" must be an object containing "
                                    "a required \"action\" field and a required non-empty "
                                    "\"expected\" postcondition object. Use \"expected\", never "
                                    "\"postcondition\". The action must be one of the allowed "
                                    "action names. Put postcondition assertions only inside "
                                    "\"step.expected\"; never put \"element_absent\" or other "
                                    "assertion names directly on the step.\n"
                                    "Example valid click step: "
                                    "{\"done\":false,\"success\":true,\"reason\":\"Select the "
                                    "visible ellipse tool.\",\"step\":{\"action\":\"click\","
                                    "\"x\":600,\"y\":300,\"expected\":{\"screen_changed\":"
                                    "{\"min_fraction\":0.001}}}}\n"
                                    "Example valid drawing step: "
                                    "{\"done\":false,\"success\":true,\"reason\":\"Draw the "
                                    "circle outline.\",\"step\":{\"action\":\"draw_path\","
                                    "\"points\":[{\"x\":600,\"y\":300},{\"x\":620,\"y\":320}],"
                                    "\"duration_seconds\":1.0,\"expected\":{\"screen_changed\":"
                                    "{\"min_fraction\":0.001}}}}\n"
                                    "For draw_path, points MUST be JSON objects with x and y fields, "
                                    "never a flat list such as [600,300,620,320] or nested arrays. "
                                    "A smooth circle should use 12-24 evenly spaced points and never "
                                    "more than 64 points. Rewrite every coordinate pair as a separate object with x and y fields.\\n"
                                    f"Validation error: {validation_detail}\n"
                                    f"Your previous invalid response was: {previous_response}"
                                ),
                            },
                        ]
                        continue
                    response_excerpt = content[:600]
                    raise CUAError(
                        "Ollama response does not match the required schema after one correction attempt. "
                        f"Validation details: {exc}. Response excerpt: {response_excerpt}"
                    ) from exc
        except urllib.error.HTTPError as exc:
            # HTTPError is also a URLError, so catch it first and preserve Ollama's
            # structured error body instead of misreporting a network connection failure.
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            try:
                parsed_error = json.loads(error_body)
                error_message = parsed_error.get("error", error_body)
            except (json.JSONDecodeError, AttributeError):
                error_message = error_body or str(exc.reason)
            error_message = str(error_message).strip()[:1200]
            raise CUAError(
                f"Ollama rejected the chat request (HTTP {exc.code} {exc.reason}): "
                f"{error_message}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CUAError(f"Could not reach local Ollama at {self.endpoint}: {exc}") from exc
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CUAError(f"Ollama returned an invalid task decision: {exc}") from exc

    @staticmethod
    def _is_manual_ui_handoff(
        goal: str, observation: Observation, decision: TaskDecision
    ) -> bool:
        """Detect a terminal refusal that delegates normal drawing UI setup to the user."""
        if not decision.done or decision.success:
            return False
        active = observation.active_window
        if active is None or not active.is_active:
            return False

        reason = decision.reason.casefold()
        asks_user_to_operate_ui = any(
            phrase in reason
            for phrase in (
                "user must select", "user needs to select", "you must select",
                "you need to select", "please select", "manually select",
                "user must click", "you must click", "please click",
                "user must choose", "you must choose",
                "user must switch", "you must switch", "user needs to switch",
                "you need to switch", "please switch", "switch to the paint",
                "switch back to paint", "different application is shown",
                "different app is shown", "target application is not the paint app",
            )
        )
        # Some vision responses contradict the OS foreground-window metadata and
        # tell the user to switch applications. Treat this as a hand-off to reconcile,
        # but only when the OS metadata itself confirms the named target application.
        if not asks_user_to_operate_ui:
            return False

        task = goal.casefold()
        if not any(word in task for word in ("draw", "circle", "ellipse", "shape", "sketch", "stroke")):
            return False

        # Do not override a legitimate foreground-window hand-off. If the task names
        # Paint/Photoshop, confirm that the active window belongs to that application.
        window_identity = f"{active.title} {active.process_name or ''}".casefold()
        app_aliases = {
            "paint": ("paint", "mspaint"),
            "photoshop": ("photoshop",),
        }
        for app, aliases in app_aliases.items():
            if app in task and not any(alias in window_identity for alias in aliases):
                return False
        return True

    @staticmethod
    def _coordinate_errors(step: TaskStep | None, screen_size: dict | None) -> list[str]:
        """Return planner-image coordinate violations before any action is dispatched."""
        if step is None or step.action not in {"click", "move_mouse", "drag", "draw_path"}:
            return []
        # Planner-only unit tests and non-visual providers may not have screenshot
        # dimensions. In that case defer to TaskRunner, which independently refuses
        # pointer dispatch when it cannot validate a captured screenshot.
        if not isinstance(screen_size, dict):
            return []
        width, height = screen_size.get("width"), screen_size.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            return []
        if step.action in {"click", "move_mouse"}:
            points = [(step.x, step.y)]
        elif step.action == "drag":
            points = [(step.start_x, step.start_y), (step.end_x, step.end_y)]
        else:
            points = [(point.x, point.y) for point in (step.points or [])]
        errors = []
        for index, (x, y) in enumerate(points):
            if x is None or y is None or not (0 <= x < width and 0 <= y < height):
                errors.append(
                    f"Point {index + 1} ({x}, {y}) is outside 0<=x<{width}, 0<=y<{height}."
                )
        return errors

    @staticmethod
    def _read_observation_image(observation: Observation) -> list[str]:
        path = observation.screenshot.path if observation.screenshot else None
        if not path or not os.path.isfile(path):
            return []
        try:
            from PIL import Image
            with Image.open(path) as source:
                image = source.convert("RGB")
                target_size = planner_image_dimensions(*image.size)
                if image.size != target_size:
                    image = image.resize(target_size, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=84, optimize=True)
            return [base64.b64encode(buffer.getvalue()).decode("ascii")]
        except (OSError, ValueError):
            return []
