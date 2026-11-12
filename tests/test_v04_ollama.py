import base64
import json
import urllib.error
from io import BytesIO

import pytest

from PIL import Image

from qwencoder_cua.agent.ollama import OllamaTaskPlanner, SYSTEM_PROMPT
from qwencoder_cua.agent.plan import TaskStep
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.observation import Observation, ScreenshotRef
from qwencoder_cua.models.window import WindowInfo


def test_planner_uses_local_ollama_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("QWENCODER_CUA_MODEL", raising=False)
    monkeypatch.delenv("QWENCODER_CUA_NUM_CTX", raising=False)
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



def test_planner_discards_whitespace_only_json_keys(monkeypatch):
    decision = {
        "done": True,
        "success": True,
        "reason": "Paint is open. The canvas, ribbon and drawing controls are visible.",
        "step": None,
        " ": " ",
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    result = planner.plan_next("Describe Paint without changing anything.", observation, [])

    assert result.done
    assert result.success
    assert result.step is None
    assert "canvas" in result.reason


def test_planner_still_rejects_meaningful_unknown_json_keys(monkeypatch):
    decision = {
        "done": True,
        "success": True,
        "reason": "Paint is open.",
        "step": None,
        "unrecognized_field": "should remain invalid",
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    with pytest.raises(CUAError, match="does not match the required schema"):
        planner.plan_next("Describe Paint without changing anything.", observation, [])



def test_planner_retries_invalid_task_step_once(monkeypatch):
    invalid = {
        "done": False,
        "success": True,
        "reason": "Select the ellipse and colour.",
        "step": {
            "element_absent": {"role": "radiobutton", "name": "Black"},
            "postcondition": {
                "element_absent": {"role": "radiobutton", "name": "White"}
            },
        },
    }
    corrected = {
        "done": False,
        "success": True,
        "reason": "Select the visible ellipse tool.",
        "step": {
            "action": "click",
            "x": 600,
            "y": 300,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(invalid)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(corrected)}}),
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(observation_id="obs", platform="windows")

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert result.step is not None
    assert result.step.action == "click"
    assert result.step.expected == {"screen_changed": {"min_fraction": 0.001}}
    assert len(requests) == 2
    assert any("schema" in item["content"].lower() for item in requests[1]["messages"] if item["role"] == "user")


def test_planner_normalizes_postcondition_alias_when_step_is_otherwise_valid(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Move to the canvas.",
        "step": {
            "action": "move_mouse",
            "x": 300,
            "y": 300,
            "postcondition": {"active_window_title_contains": "Paint"},
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

    result = planner.plan_next("Move the pointer to the canvas.", observation, [])

    assert result.step.action == "move_mouse"
    assert result.step.expected == {"active_window_title_contains": "Paint"}


def test_prompt_requires_exact_taskstep_fields():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "action field is mandatory" in normalized
    assert "non-empty expected postcondition" in normalized
    assert 'never use "postcondition"' in normalized



def test_planner_drops_unsupported_semantic_alias_when_screen_change_is_valid(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Select the ellipse tool.",
        "step": {
            "action": "click",
            "x": 700,
            "y": 300,
            "expected": {
                "screen_changed": {"min_fraction": 0.001},
                "element_abs": {"role": "radiobutton", "name": "Black"},
            },
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

    result = planner.plan_next("Select the Paint ellipse tool.", observation, [])

    assert result.step is not None
    assert result.step.expected == {"screen_changed": {"min_fraction": 0.001}}


def test_planner_preserves_supported_semantic_checks_alongside_screen_change(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Click a visible control.",
        "step": {
            "action": "click",
            "x": 700,
            "y": 300,
            "expected": {
                "screen_changed": {"min_fraction": 0.001},
                "active_window_title_contains": "Paint",
            },
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

    result = planner.plan_next("Click a Paint control.", observation, [])

    assert result.step.expected == {
        "screen_changed": {"min_fraction": 0.001},
        "active_window_title_contains": "Paint",
    }


def test_prompt_prefers_visual_verification_for_coordinate_ui_actions():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "prefer exactly one reliable visual postcondition" in normalized
    assert "those controls usually remain present after being selected" in normalized



def test_planner_retries_out_of_range_coordinates_once(monkeypatch):
    invalid = {
        "done": False,
        "success": True,
        "reason": "Click the ellipse tool.",
        "step": {
            "action": "click",
            "x": 6000,
            "y": 280,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    corrected = {
        "done": False,
        "success": True,
        "reason": "Click the ellipse tool inside the visible ribbon.",
        "step": {
            "action": "click",
            "x": 800,
            "y": 280,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(invalid)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(corrected)}}),
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        screenshot=ScreenshotRef(path=None, width=3440, height=1440),
    )

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert result.step is not None
    assert result.step.action == "click"
    assert result.step.x == 800
    assert len(requests) == 2
    correction = requests[1]["messages"][-1]["content"]
    assert "Planner image dimensions" in correction
    assert "Point 1 (6000, 280)" in correction


def test_planner_rejects_coordinates_still_out_of_range_after_retry(monkeypatch):
    invalid = {
        "done": False,
        "success": True,
        "reason": "Click Paint.",
        "step": {
            "action": "click",
            "x": 6000,
            "y": 280,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(invalid)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(invalid)}}),
    ]
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: responses.pop(0),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        screenshot=ScreenshotRef(path=None, width=3440, height=1440),
    )

    with pytest.raises(CUAError, match="out-of-range pointer coordinates"):
        planner.plan_next("Draw in Paint.", observation, [])


def test_coordinate_errors_validate_all_path_points_and_drag_endpoints():
    size = {"width": 1280, "height": 536}
    bad_click = TaskStep(
        action="click", x=6000, y=280,
        expected={"screen_changed": {"min_fraction": 0.001}},
    )
    assert OllamaTaskPlanner._coordinate_errors(bad_click, size)

    bad_drag = TaskStep(
        action="drag", start_x=10, start_y=10, end_x=1300, end_y=20,
        expected={"screen_changed": {"min_fraction": 0.001}},
    )
    assert OllamaTaskPlanner._coordinate_errors(bad_drag, size)

    bad_path = TaskStep(
        action="draw_path",
        points=[{"x": 20, "y": 20}, {"x": 1300, "y": 20}],
        expected={"screen_changed": {"min_fraction": 0.001}},
    )
    assert OllamaTaskPlanner._coordinate_errors(bad_path, size) == [
        "Point 2 (1300, 20) is outside 0<=x<1280, 0<=y<536."
    ]


def test_prompt_has_strict_planner_image_coordinate_bounds():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "0 <= x < screen_size.width" in normalized
    assert "Coordinates returned in actions MUST use" in normalized
    assert "do not guess" in normalized



def test_planner_retries_manual_paint_ui_handoff_when_paint_is_active(monkeypatch):
    manual_handoff = {
        "done": True,
        "success": False,
        "reason": (
            "The user must select the red color from the color palette, then select "
            "the circle shape from the shape menu, and finally click on the canvas."
        ),
        "step": None,
    }
    actionable = {
        "done": False,
        "success": True,
        "reason": "Select the visible red color swatch.",
        "step": {
            "action": "click",
            "x": 420,
            "y": 90,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(manual_handoff)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(actionable)}}),
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        active_window=WindowInfo(
            id="1", title="Untitled - Paint", process_name="mspaint.exe", is_active=True
        ),
    )

    result = planner.plan_next(
        "Draw a smooth red circle near the centre of the blank Paint canvas.", observation, []
    )

    assert not result.done
    assert result.step is not None
    assert result.step.action == "click"
    assert len(requests) == 2
    correction = requests[1]["messages"][-1]["content"].lower()
    assert "target application is already active" in correction
    assert "do not tell the user" in correction


def test_planner_does_not_override_manual_handoff_when_paint_is_not_active(monkeypatch):
    manual_handoff = {
        "done": True,
        "success": False,
        "reason": "The user must select the red color from the palette.",
        "step": None,
    }
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeOllamaResponse({"message": {"content": json.dumps(manual_handoff)}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        active_window=WindowInfo(id="2", title="Untitled - Notepad", is_active=True),
    )

    result = planner.plan_next(
        "Draw a smooth red circle in Paint.", observation, []
    )

    assert result.done
    assert not result.success
    assert len(calls) == 1


def test_planner_stops_after_repeated_manual_ui_handoff(monkeypatch):
    manual_handoff = {
        "done": True,
        "success": False,
        "reason": "The user must select the red color from the palette.",
        "step": None,
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(manual_handoff)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(manual_handoff)}}),
    ]
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        active_window=WindowInfo(
            id="1", title="Untitled - Paint", process_name="mspaint.exe", is_active=True
        ),
    )

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert result.done
    assert not result.success
    assert len(calls) == 2
    assert "no desktop action was dispatched" in result.reason.lower()



def test_prompt_treats_normal_ui_setup_as_agent_work():
    normalized = " ".join(SYSTEM_PROMPT.split()).lower()
    assert "normal ui setup is part of the task, not a blocker" in normalized
    assert "never return a terminal failure saying the user must select" in normalized
