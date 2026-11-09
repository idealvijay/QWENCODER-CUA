import base64
from io import BytesIO

from PIL import Image

from qwencoder_cua.agent.ollama import OllamaTaskPlanner
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
