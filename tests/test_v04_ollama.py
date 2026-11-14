import base64
import json
import urllib.error
from io import BytesIO

import pytest

from PIL import Image

from qwencoder_cua.agent.ollama import OllamaTaskPlanner, SYSTEM_PROMPT
from qwencoder_cua.agent.plan import TaskStep
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect
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
    assert planner.num_ctx == 20000


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
        assert resized.size == (448, 269)


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
        "reason": "Activate a semantic Paint control.",
        "step": {
            "action": "click_element",
            "selector": {"role": "button", "name": "Paint control"},
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

    result = planner.plan_next("Activate a semantic Paint control.", observation, [])

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
            "x": 400,
            "y": 140,
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
    assert result.step.x == 400
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
    size = {"width": 448, "height": 188}
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
        "Point 2 (1300, 20) is outside 0<=x<448, 0<=y<188."
    ]


def test_prompt_has_strict_planner_image_coordinate_bounds():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "0 <= x < screen_size.width" in normalized
    assert "Coordinates returned in actions MUST use" in normalized
    assert "do not guess" in normalized
    assert "maximum 448x448" in normalized



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
    assert "os foreground-window api reports" in correction
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



def test_planner_retries_when_model_contradicts_active_paint_window(monkeypatch):
    contradiction = {
        "done": True,
        "success": False,
        "reason": (
            "The current active window is Paint, but the target application is not the "
            "Paint app and a different application is shown on the screen. The user must "
            "switch to the Paint app to draw a circle."
        ),
        "step": None,
    }
    actionable = {
        "done": False,
        "success": True,
        "reason": "Paint is visible; select the red swatch.",
        "step": {
            "action": "click",
            "x": 430,
            "y": 88,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(contradiction)}}),
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

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert not result.done
    assert result.step is not None and result.step.action == "click"
    assert len(requests) == 2
    correction = requests[1]["messages"][-1]["content"]
    assert "OS foreground-window API reports" in correction
    assert "screenshot genuinely shows a different app" in correction


def test_planner_does_not_retry_app_mismatch_when_other_app_is_foreground(monkeypatch):
    contradiction = {
        "done": True,
        "success": False,
        "reason": (
            "The current active window is not Paint. A different application is shown. "
            "The user must switch to the Paint app."
        ),
        "step": None,
    }
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeOllamaResponse({"message": {"content": json.dumps(contradiction)}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        active_window=WindowInfo(
            id="2", title="Untitled - Notepad", process_name="notepad.exe", is_active=True
        ),
    )

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert result.done and not result.success
    assert len(calls) == 1


def test_planner_reports_unresolved_paint_screenshot_mismatch_safely(monkeypatch):
    contradiction = {
        "done": True,
        "success": False,
        "reason": (
            "The current active window is Paint, but a different application is shown. "
            "The user must switch to Paint."
        ),
        "step": None,
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(contradiction)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(contradiction)}}),
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

    assert result.done and not result.success
    assert len(calls) == 2
    assert "screenshot/window mismatch" in result.reason.lower()
    assert "no desktop action was dispatched" in result.reason.lower()



def test_planner_drops_semantic_postconditions_for_pointer_actions(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Select the red swatch.",
        "step": {
            "action": "click",
            "x": 430,
            "y": 88,
            "expected": {
                "screen_changed": {"min_fraction": 0.001},
                "element_present": {"role": "button", "name": "Red"},
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

    result = planner.plan_next("Select red in Paint.", observation, [])

    assert result.step is not None
    assert result.step.expected == {"screen_changed": {"min_fraction": 0.001}}


def test_planner_preserves_semantic_postconditions_for_semantic_actions(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Activate the ellipse control.",
        "step": {
            "action": "click_element",
            "selector": {"role": "button", "name": "Ellipse"},
            "expected": {
                "screen_changed": {"min_fraction": 0.001},
                "element_present": {"role": "button", "name": "Ellipse"},
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

    result = planner.plan_next("Activate the ellipse control.", observation, [])

    assert result.step is not None
    assert result.step.expected == {
        "screen_changed": {"min_fraction": 0.001},
        "element_present": {"role": "button", "name": "Ellipse"},
    }



def test_planner_normalizes_flat_draw_path_coordinates(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Draw the circle outline.",
        "step": {
            "action": "draw_path",
            "points": [coordinate for index in range(37) for coordinate in (600 + index, 200 + index)],
            "duration_seconds": 1.0,
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        screenshot=ScreenshotRef(path=None, width=1280, height=800),
    )

    result = planner.plan_next("Draw a red circle in Paint.", observation, [])

    assert result.step is not None
    assert result.step.action == "draw_path"
    assert len(result.step.points) == 37
    assert [(point.x, point.y) for point in result.step.points[:3]] == [
        (600, 200), (601, 201), (602, 202)
    ]


def test_planner_normalizes_pair_array_draw_path_coordinates(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Draw a short path.",
        "step": {
            "action": "draw_path",
            "points": [[600, 200], [620, 220]],
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        }),
    )
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        screenshot=ScreenshotRef(path=None, width=1280, height=800),
    )

    result = planner.plan_next("Draw a short path.", observation, [])

    assert result.step is not None
    assert [(point.x, point.y) for point in result.step.points] == [(600, 200), (620, 220)]


def test_planner_does_not_truncate_draw_path_over_64_waypoints(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Draw a path.",
        "step": {
            "action": "draw_path",
            "points": [coordinate for index in range(65) for coordinate in (index, index)],
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    responses = [
        FakeOllamaResponse({"message": {"content": json.dumps(decision)}}),
        FakeOllamaResponse({"message": {"content": json.dumps(decision)}}),
    ]
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append(1)
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs",
        platform="windows",
        screenshot=ScreenshotRef(path=None, width=1280, height=800),
    )

    with pytest.raises(CUAError, match="does not match the required schema") as caught:
        planner.plan_next("Draw a path.", observation, [])

    assert "at most 64 items" in str(caught.value)
    assert len(calls) == 2


def test_prompt_requires_object_waypoints_and_prefers_native_paint_ellipse():
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert 'points (2-64 objects, each exactly {"x": int, "y": int})' in normalized
    assert "strongly prefer the built-in Ellipse/Oval shape" in normalized
    assert "12-24 evenly distributed waypoints" in normalized
    assert "Never return a flat number list or nested coordinate arrays." in normalized



def test_planner_receives_named_targets_and_can_choose_one(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Select the ellipse shape using its detected target.",
        "step": {
            "action": "click_target",
            "target_id": "paint.shape.ellipse",
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs-1",
        platform="windows",
        active_window=WindowInfo(
            id="1", title="Untitled - Paint", process_name="mspaint.exe", is_active=True
        ),
        elements=[
            UIElement(
                id="ellipse-1",
                role="button",
                name="Ellipse",
                bounds=Rect(x=500, y=80, width=40, height=28),
            )
        ],
        accessibility_available=True,
    )

    result = planner.plan_next("Select the ellipse in Paint.", observation, [])

    assert result.step is not None
    assert result.step.action == "click_target"
    assert result.step.target_id == "paint.shape.ellipse"
    context = json.loads(captured["payload"]["messages"][1]["content"])
    assert context["available_targets"][0]["target_id"] == "paint.shape.ellipse"
    assert context["available_targets"][0]["center"] == {"x": 520, "y": 94}
    assert "click_target" in SYSTEM_PROMPT



def test_planner_scales_named_target_bounds_to_resized_image(monkeypatch):
    decision = {
        "done": False,
        "success": True,
        "reason": "Click the detected target.",
        "step": {
            "action": "click_target",
            "target_id": "paint.shape.ellipse",
            "expected": {"screen_changed": {"min_fraction": 0.001}},
        },
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeOllamaResponse({
            "message": {"content": json.dumps(decision)}
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs-scale",
        platform="windows",
        active_window=WindowInfo(
            id="1", title="Untitled - Paint", process_name="mspaint.exe", is_active=True
        ),
        screenshot=ScreenshotRef(path=None, width=2000, height=1000),
        elements=[
            UIElement(
                id="ellipse",
                role="button",
                name="Ellipse",
                bounds=Rect(x=1000, y=500, width=200, height=100),
            )
        ],
    )

    planner.plan_next("Select ellipse.", observation, [])

    context = json.loads(captured["payload"]["messages"][1]["content"])
    target = context["available_targets"][0]
    assert context["screen_size"] == {"width": 448, "height": 224}
    assert context["capture_size"] == {"width": 2000, "height": 1000}
    assert target["coordinate_space"] == "planner_image_pixels"
    assert target["bounds"] == {"x": 224, "y": 112, "width": 45, "height": 22}
    assert target["center"] == {"x": 246, "y": 123}


def test_planner_accepts_injected_target_detector():
    from qwencoder_cua.perception.target_detector import TargetDetector

    def custom_visual_detector(observation):
        return []

    detector = TargetDetector(visual_detectors=[custom_visual_detector])
    planner = OllamaTaskPlanner(
        model="minicpm-v4.5:q4_0", target_detector=detector
    )
    assert planner.target_detector is detector
