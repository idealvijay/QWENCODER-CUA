from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from typing import Any

from qwencoder_cua.agent.plan import TaskDecision, TaskStep
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.observation import Observation


SYSTEM_PROMPT = """You are the planning component of QWENCODER CUA, a local desktop automation agent.
Return exactly one JSON object matching:
{"done": boolean, "success": boolean, "reason": string, "step": TaskStep object or null}

When done=true, step must be null. Set success=true only when the user's goal is achieved.
If blocked, lacking required information, or unable to complete safely, set done=true and success=false.
Otherwise return exactly one next action.
Allowed actions:
- click: x, y
- type_text: text
- press_key: key (examples: enter, tab, ctrl+c)
- scroll: dx and/or dy
- click_element: selector
- focus_element: selector
- set_element_value: selector and value

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
                 timeout_seconds: float = 45.0):
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
            "accessible_elements": elements,
            "completed_steps": [item.model_dump() for item in history[-12:]],
        }
        message = {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
        images = self._read_observation_image(observation) if self.include_images else []
        if images:
            message["images"] = images
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, message],
            "stream": False,
            "format": "json",
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body.get("message", {}).get("content")
            if not isinstance(content, str):
                raise CUAError("Ollama returned no JSON message content.")
            decision_data = json.loads(content)
            return TaskDecision.model_validate(decision_data)
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
                image.thumbnail((1280, 800))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=84, optimize=True)
            return [base64.b64encode(buffer.getvalue()).decode("ascii")]
        except (OSError, ValueError):
            return []
