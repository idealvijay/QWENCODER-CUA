import base64
import json
import urllib.error
from io import BytesIO

import pytest

from PIL import Image

from qwencoder_cua.agent.ollama import OllamaTaskPlanner, SYSTEM_PROMPT
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.observation import Observation, ScreenshotRef


def test_planner_uses_local_ollama_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("QWENCODER_CUA_MODEL", raising=False)
    planner = OllamaTaskPlanner()
    assert planner.endpoint == "http://127.0.0.1:11434/api/chat"
    assert planner.model == "minicpm-v4.5:q4_0"
    assert planner.include_images


def test_screenshot_is_resized_and_encoded(tmp_path):
    path = tmp_path / "screen.png"
    Image.new("RGB", (2000, 1200), "blue").save(path)
    observation = Observation(
        observation_id="obs", platform="test",
        screenshot=ScreenshotRef(path=str(path), width=2000, height=1200),
    )
    images = OllamaTaskPlanner._read_observation_image(observation)
    assert len(images) == 1
    raw = base64.b64decode(images[0])
    assert raw.startswith(b"\xff\xd8")
    with Image.open(BytesIO(raw)) as resized:
        assert resized.width <= 1280
        assert resized.height <= 800


def test_text_only_model_does_not_receive_image_payload():
    planner = OllamaTaskPlanner(model="qwen2.5-coder:7b")
    assert not planner.include_images



class FakeOllamaResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_prompt_explains_how_to_finish_read_only_goals():
    assert "Some goals are read-only" in SYSTEM_PROMPT
    assert 'put the answer' in SYSTEM_PROMPT
    assert "Do not invent a click" in SYSTEM_PROMPT


def test_planner_accepts_read_only_answer_from_ollama(monkeypatch):
    decision = {
        "done": True,
        "success": True,
        "reason": "The foreground application is Paint. Its visible controls include the ribbon and canvas.",
        "step": None,
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    result = planner.plan_next("Describe the visible application without changes.", observation, [])

    assert result.done
    assert result.success
    assert result.step is None
    assert "Paint" in result.reason


def test_planner_reports_invalid_decision_as_cua_error(monkeypatch):
    invalid_decision = {"done": False, "success": True, "reason": "No actions needed.", "step": None}
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(invalid_decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    with pytest.raises(CUAError, match="does not match the required schema"):
        planner.plan_next("Describe the visible application without changes.", observation, [])



def test_prompt_explains_target_application_must_be_foreground():
    assert "not the active window" in SYSTEM_PROMPT
    assert "do not invent a click" in SYSTEM_PROMPT
    normalized_prompt = " ".join(SYSTEM_PROMPT.split())
    assert "bring the target application to the foreground" in normalized_prompt


def test_completed_decision_discards_stray_model_action(monkeypatch):
    # A few local models return done=true but still attach a malformed or
    # contradictory step. A terminal decision must never dispatch that step.
    decision = {
        "done": True,
        "success": False,
        "reason": "Paint is not the active application. Bring Paint to the foreground and retry.",
        "step": {
            "click": {"element_absent": {"role": "window", "name": "Paint"}},
            "expected_postcondition": {"active_window_title_contains": "Paint"},
        },
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    result = planner.plan_next("Describe the Paint interface without changes.", observation, [])

    assert result.done
    assert not result.success
    assert result.step is None
    assert "Paint is not the active application" in result.reason



def test_planner_shows_ollama_http_error_body(monkeypatch):
    error_body = json.dumps({"error": "image payload is not supported by this model"}).encode("utf-8")
    http_error = urllib.error.HTTPError(
        "http://127.0.0.1:11434/api/chat",
        400,
        "Bad Request",
        hdrs=None,
        fp=BytesIO(error_body),
    )

    def raise_http_error(*args, **kwargs):
        raise http_error

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    with pytest.raises(CUAError, match="HTTP 400 Bad Request") as caught:
        planner.plan_next("Describe the desktop.", observation, [])

    assert "image payload is not supported by this model" in str(caught.value)
