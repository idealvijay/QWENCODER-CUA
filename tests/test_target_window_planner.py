import base64
import io
import json

from PIL import Image

from qwencoder_cua.agent.ollama import OllamaTaskPlanner, SYSTEM_PROMPT
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.observation import Observation, ScreenshotRef
from qwencoder_cua.models.window import WindowInfo


class FakeOllamaResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def test_planner_context_distinguishes_target_window_from_foreground_terminal(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        captured["payload"] = payload
        return FakeOllamaResponse({
            "message": {
                "content": json.dumps({
                    "done": True,
                    "success": True,
                    "reason": "I am inspecting the selected Paint window.",
                    "step": None,
                })
            }
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    observation = Observation(
        observation_id="obs-window",
        platform="windows",
        active_window=WindowInfo(
            id="10", title="Command Prompt", process_id=111, process_name="cmd.exe",
            is_active=True,
        ),
        target_window=WindowInfo(
            id="42", title="Untitled - Paint", process_id=222, process_name="mspaint.exe",
            is_active=False,
        ),
        screenshot=ScreenshotRef(
            path=None, width=1200, height=800, origin_x=300, origin_y=200,
            coordinate_space="window",
        ),
    )

    result = planner.plan_next("Describe the selected Paint window.", observation, [])
    context = json.loads(captured["payload"]["messages"][1]["content"])

    assert result.done and result.success
    assert context["active_window"]["process_name"] == "cmd.exe"
    assert context["target_window"]["process_name"] == "mspaint.exe"
    assert context["capture_coordinate_space"] == "window"
    assert context["capture_origin"] == {"x": 300, "y": 200}
    assert context["desktop_size"] is None
    assert context["screen_size"] == {"width": 600, "height": 400}
    assert context["capture_size"] == {"width": 1200, "height": 800}
    assert captured["payload"]["options"]["num_ctx"] == 20480
    assert "Treat it as authoritative" in SYSTEM_PROMPT
    assert "capture_size" in SYSTEM_PROMPT



def test_num_ctx_is_hard_capped_at_20480(monkeypatch):
    monkeypatch.setenv("QWENCODER_CUA_NUM_CTX", "32768")
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    assert planner.num_ctx == 20480


def test_vision_image_is_downsampled_but_original_capture_is_preserved(tmp_path):
    screenshot_path = tmp_path / "paint-window.png"
    original = Image.new("RGB", (1200, 800), "white")
    original.save(screenshot_path)
    observation = Observation(
        observation_id="obs-image",
        platform="windows",
        screenshot=ScreenshotRef(
            path=str(screenshot_path),
            width=1200,
            height=800,
            origin_x=300,
            origin_y=200,
            coordinate_space="window",
        ),
    )

    encoded = OllamaTaskPlanner._read_observation_image(observation)
    assert len(encoded) == 1
    model_image = Image.open(io.BytesIO(base64.b64decode(encoded[0])))
    assert model_image.size == (600, 400)

    # The on-disk original remains full resolution for verification and coordinate mapping.
    with Image.open(screenshot_path) as retained_original:
        assert retained_original.size == (1200, 800)



def test_prompt_context_is_compacted_to_leave_room_for_image_tokens(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeOllamaResponse({
            "message": {
                "content": json.dumps({
                    "done": True,
                    "success": True,
                    "reason": "The visible controls are available.",
                    "step": None,
                })
            }
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaTaskPlanner(model="minicpm-v4.5:q4_0")
    elements = [
        UIElement(
            id=f"element-{index}",
            role="button",
            name=("Control " + str(index) + " " + "N" * 160),
            value="V" * 160,
            automation_id="A" * 100,
            class_name="C" * 100,
            parent_name="P" * 120,
        )
        for index in range(80)
    ]
    observation = Observation(
        observation_id="obs-large-tree",
        platform="windows",
        elements=elements,
    )

    planner.plan_next("Inspect the visible controls.", observation, [])

    user_context = captured["payload"]["messages"][1]["content"]
    parsed = json.loads(user_context)
    assert len(user_context) <= 24000
    assert len(parsed["accessible_elements"]) < len(elements)
