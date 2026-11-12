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
- focus_element: selector
- set_element_value: selector and value
- move_mouse: x, y
- drag: start_x, start_y, end_x, end_y, optional button and duration_seconds
- draw_path: points (2-64 {x, y} waypoints), optional button and duration_seconds

Pointer coordinates are measured in the resized image shown to you (the
`screen_size` field), not the full desktop. The runner automatically maps them to desktop
pixels using `desktop_size`. Keep every point within `screen_size` and inside the drawable
canvas rectangle; never target the toolbar, ribbon, status bar or title bar as a drawing point.

For drawing tasks, distinguish the canvas from surrounding application chrome. A blank
white/transparent canvas is normal and is not evidence that a tool or colour is missing.
The user's statement that the canvas is blank is reliable unless clear visible artwork
contradicts it. Do not refuse a drawing task because the canvas "does not look empty" unless
you can identify specific visible marks inside the canvas itself. Ignore colour swatches,
tool icons, selection handles and other UI elements when assessing whether the canvas contains
artwork. If the requested tool or colour is not selected, use visible, unambiguous controls to
select it as normal planner steps; do not ask the user to do this when controls are visible.
For a circle in Paint, prefer the built-in ellipse shape with no fill and a red outline if those
controls are visible; otherwise use a closed draw_path. Do not claim a tool or shape is absent
without checking the screenshot and accessible elements.

For a Paint/Photoshop stroke, identify the drawable canvas first. Use draw_path (one atomic
press/move/release) for a freehand path; use drag for a straight drag or a native
ellipse/rectangle tool gesture. A draw_path or drag action must request a screen_changed
postcondition, normally with min_fraction 0.001.

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
                        # Accept the common natural-language alias, but do not infer action.
                        if "expected" not in step_data and isinstance(step_data.get("postcondition"), dict):
                            step_data["expected"] = step_data.pop("postcondition")
                    # A terminal decision must never dispatch any attached action.
                    if decision_data.get("done") is True and decision_data.get("step") is not None:
                        decision_data["step"] = None

                try:
                    return TaskDecision.model_validate(decision_data)
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
