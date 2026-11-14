import json

from qwencoder_cua.agent.scene_planner import OllamaScenePlanner, SCENE_SYSTEM_PROMPT


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def test_scene_planner_requests_structured_scene_and_uses_caller_canvas(monkeypatch):
    response_scene = {
        "title": "Sun",
        "canvas_target_id": "model-invented-id",
        "objects": [{
            "object_id": "sun",
            "name": "Sun",
            "primitive": "ellipse",
            "bounds": {"x": 0.7, "y": 0.1, "width": 0.15, "height": 0.15},
            "points": [],
            "style": {"stroke": "#000000", "fill": None, "stroke_width": 1.0, "opacity": 1.0},
            "z_index": 0,
            "closed": False,
        }],
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"message": {"content": json.dumps(response_scene)}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    planner = OllamaScenePlanner(model="qwen2.5-coder:7b")
    scene = planner.plan("Draw a simple sun.", canvas_target_id="paint.canvas.main")

    assert scene.canvas_target_id == "paint.canvas.main"
    assert scene.objects[0].object_id == "sun"
    assert captured["payload"]["format"]["title"] == "ScenePlan"
    assert "normalized" in SCENE_SYSTEM_PROMPT


def test_scene_planner_rejects_empty_brief_and_canvas_id():
    planner = OllamaScenePlanner(model="qwen2.5-coder:7b")
    try:
        planner.plan(" ", canvas_target_id="paint.canvas.main")
        assert False, "Expected empty brief to be rejected"
    except ValueError as exc:
        assert "brief" in str(exc)

    try:
        planner.plan("Draw a line.", canvas_target_id=" ")
        assert False, "Expected empty canvas target to be rejected"
    except ValueError as exc:
        assert "canvas_target_id" in str(exc)
