import json

from qwencoder_cua.agent.ollama import OllamaTaskPlanner, SYSTEM_PROMPT
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
    assert context["screen_size"] == {"width": 1200, "height": 800}
    assert "Treat it as authoritative" in SYSTEM_PROMPT
