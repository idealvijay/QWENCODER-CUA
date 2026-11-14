from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.scene import ScenePlan


SCENE_SYSTEM_PROMPT = """You are the scene-planning component of QWENCODER CUA.
Convert the user's artwork brief into one structured ScenePlan JSON object.
Do not describe desktop UI actions. Do not return Markdown or code fences.

Coordinate system:
- Every point and rectangle is normalized to the drawable canvas: (0, 0) is top-left,
  (1, 1) is bottom-right. Keep every object fully inside 0..1.
- Use simple, deliberate geometry. Prefer ellipse, rectangle, line, polygon and path.
- Ellipse and rectangle require a normalized bounds object with x, y, width and height.
- Line, polygon and path use a points array of {x, y} objects. Polygon needs at least 3 points.
- Each object has object_id, name, primitive, style, z_index and closed.
- Use at most 32 objects and at most 512 explicit points in total.
- Order z_index from back to front. Avoid unnecessary overlaps and excessive detail.
- Keep a small margin from the edge unless the brief explicitly needs a full-bleed object.

Style limitations:
- Use outline-only shapes: fill must be null and opacity must be 1.0.
- Use stroke colours as #RRGGBB hex strings and stroke_width 1.0 unless the user explicitly
  asks for another width. The drawing executor needs a style_applier to set non-default colour
  or width in the target application. It never silently applies a style it cannot support.
- Do not attempt gradients, text, raster images, blur, masks, clipping or layer effects.

Return exactly the ScenePlan shape. The caller supplies canvas_target_id; copy it exactly.
The scene title should be concise. Use stable, unique object_id values containing letters,
numbers, underscores or hyphens. The result must be concrete enough to execute without
further interpretation.
"""


class OllamaScenePlanner:
    """Generate a normalized ScenePlan using a local Ollama chat model."""

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        num_ctx: int | None = None,
        max_objects: int = 32,
        max_points: int = 512,
    ):
        self.endpoint = (
            endpoint or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        if not self.endpoint.endswith("/api/chat"):
            self.endpoint = (
                self.endpoint + "/chat"
                if self.endpoint.endswith("/api")
                else self.endpoint + "/api/chat"
            )
        self.model = (
            model
            or os.environ.get("QWENCODER_CUA_SCENE_MODEL")
            or os.environ.get("QWENCODER_CUA_MODEL")
            or os.environ.get("MODEL")
            or "qwen2.5-coder:7b"
        )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        raw_num_ctx = num_ctx if num_ctx is not None else os.environ.get(
            "QWENCODER_CUA_NUM_CTX", "8192"
        )
        try:
            self.num_ctx = int(raw_num_ctx)
        except (TypeError, ValueError) as exc:
            raise ValueError("QWENCODER_CUA_NUM_CTX must be a positive integer.") from exc
        if not 2048 <= self.num_ctx <= 131072:
            raise ValueError("num_ctx must be between 2048 and 131072 tokens.")
        if not 1 <= max_objects <= 32:
            raise ValueError("max_objects must be between 1 and 32")
        if not 1 <= max_points <= 512:
            raise ValueError("max_points must be between 1 and 512")
        self.max_objects = max_objects
        self.max_points = max_points

    def plan(self, brief: str, *, canvas_target_id: str) -> ScenePlan:
        if not brief or not brief.strip():
            raise ValueError("brief must not be empty")
        if not canvas_target_id or not canvas_target_id.strip():
            raise ValueError("canvas_target_id must not be empty")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SCENE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({
                    "brief": brief.strip(),
                    "canvas_target_id": canvas_target_id,
                    "limits": {
                        "max_objects": self.max_objects,
                        "max_explicit_points": self.max_points,
                    },
                }, ensure_ascii=False),
            },
        ]
        last_error = ""
        for attempt in range(2):
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": ScenePlan.model_json_schema(),
                "options": {"num_ctx": self.num_ctx},
            }
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            content = ""
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body.get("message", {}).get("content")
                if not isinstance(content, str):
                    raise CUAError("Ollama returned no scene JSON content.")
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise CUAError("Ollama scene response must be a JSON object.")
                # The target identity is provided by the caller, never trusted to model output.
                data["canvas_target_id"] = canvas_target_id
                scene = ScenePlan.model_validate(data)
                if len(scene.objects) > self.max_objects:
                    raise ValueError(
                        f"Scene has {len(scene.objects)} objects; maximum is {self.max_objects}."
                    )
                explicit_points = sum(len(item.points) for item in scene.objects)
                if explicit_points > self.max_points:
                    raise ValueError(
                        f"Scene has {explicit_points} explicit points; maximum is {self.max_points}."
                    )
                return scene
            except urllib.error.HTTPError as exc:
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    error_body = ""
                raise CUAError(
                    f"Ollama rejected the scene request (HTTP {exc.code}): "
                    f"{error_body or exc.reason}"
                ) from exc
            except urllib.error.URLError as exc:
                raise CUAError(f"Could not reach local Ollama at {self.endpoint}: {exc}") from exc
            except ValidationError as exc:
                last_error = str(exc)[:1600]
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                last_error = f"Invalid scene JSON: {exc}"
            except ValueError as exc:
                last_error = str(exc)
            if attempt == 0:
                messages.extend([
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "The previous scene did not satisfy the ScenePlan schema or limits. "
                            "Correct the JSON and return one complete ScenePlan object. "
                            f"Validation issue: {last_error}"
                        ),
                    },
                ])

        raise CUAError(f"Ollama could not produce a valid scene after one correction: {last_error}")
