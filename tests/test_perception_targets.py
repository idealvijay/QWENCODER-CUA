from PIL import Image, ImageDraw
import pytest

from qwencoder_cua.core.target_errors import StaleTargetError, TargetNotFoundError
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.models.window import WindowInfo
from qwencoder_cua.perception.accessibility_detector import AccessibilityTargetDetector
from qwencoder_cua.perception.color_detector import ColorSwatchDetector
from qwencoder_cua.perception.target_registry import TargetRegistry
from qwencoder_cua.perception.target_detector import TargetDetector


def test_accessibility_detector_assigns_named_paint_target_ids():
    observation = Observation(
        observation_id="obs-1",
        platform="windows",
        active_window=WindowInfo(
            id="1", title="Untitled - Paint", process_name="mspaint.exe", is_active=True
        ),
        elements=[
            UIElement(
                id="e1", role="button", name="Red",
                bounds=Rect(x=10, y=20, width=20, height=20),
            ),
            UIElement(
                id="e2", role="button", name="Ellipse",
                bounds=Rect(x=40, y=20, width=30, height=20),
            ),
            UIElement(
                id="e3", role="pane", name="Canvas",
                bounds=Rect(x=100, y=100, width=500, height=400),
            ),
        ],
        accessibility_available=True,
    )
    targets = AccessibilityTargetDetector().detect(observation)

    assert [target.target_id for target in targets] == [
        "paint.color.red", "paint.shape.ellipse", "paint.canvas.canvas"
    ]
    assert [target.kind for target in targets] == ["color", "shape", "canvas"]


def test_registry_rejects_stale_targets_and_stale_observations():
    observation = Observation(observation_id="obs-a", platform="windows")
    target = AccessibilityTargetDetector().detect(Observation(
        observation_id="obs-a",
        platform="windows",
        active_window=WindowInfo(id="1", title="Paint", is_active=True),
        elements=[UIElement(
            id="red", role="button", name="Red",
            bounds=Rect(x=10, y=10, width=10, height=10),
        )],
    ))[0]
    registry = TargetRegistry(observation.observation_id, [target])

    with pytest.raises(StaleTargetError):
        registry.resolve(target.target_id, observation_id="obs-b")
    with pytest.raises(StaleTargetError):
        TargetRegistry("obs-b", [target])


def test_registry_resolves_named_target_and_emits_prompt_context():
    target = AccessibilityTargetDetector().detect(Observation(
        observation_id="obs-1",
        platform="windows",
        active_window=WindowInfo(id="1", title="Paint", is_active=True),
        elements=[UIElement(
            id="ellipse", role="button", name="Ellipse",
            bounds=Rect(x=20, y=30, width=40, height=24),
        )],
    ))[0]
    registry = TargetRegistry("obs-1", [target])

    resolved = registry.resolve(target.target_id, observation_id="obs-1")
    context = registry.prompt_context(observation_id="obs-1")

    assert resolved.center.model_dump() == {"x": 40, "y": 42}
    assert context[0]["target_id"] == "paint.shape.ellipse"
    assert context[0]["bounds"] == {"x": 20, "y": 30, "width": 40, "height": 24}


def test_registry_rejects_low_confidence_target():
    target = AccessibilityTargetDetector().detect(Observation(
        observation_id="obs-1",
        platform="windows",
        active_window=WindowInfo(id="1", title="Paint", is_active=True),
        elements=[UIElement(
            id="ellipse", role="button", name="Ellipse",
            bounds=Rect(x=20, y=30, width=40, height=24),
        )],
    ))[0].model_copy(update={"confidence": 0.4})
    registry = TargetRegistry("obs-1", [target])
    with pytest.raises(TargetNotFoundError, match="confidence"):
        registry.resolve(target.target_id, observation_id="obs-1")


def test_color_swatch_detector_finds_target_only_inside_requested_palette_region():
    image = Image.new("RGB", (160, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 39, 39), fill=(255, 0, 0))
    draw.rectangle((90, 20, 120, 50), fill=(255, 0, 0))  # large region is ignored
    targets = ColorSwatchDetector().detect(
        image,
        observation_id="obs-1",
        search_region=Rect(x=0, y=0, width=70, height=70),
        color_name="red",
        rgb=(255, 0, 0),
        minimum_area=16,
    )

    assert len(targets) == 1
    assert targets[0].target_id == "paint.color.red"
    assert targets[0].bounds == Rect(x=20, y=20, width=20, height=20)
    assert targets[0].center.model_dump() == {"x": 30, "y": 30}



def test_combined_target_detector_merges_visual_and_accessibility_targets():
    observation = Observation(observation_id="obs-1", platform="windows")
    visual_target = UITarget(
        target_id="paint.color.red",
        label="Red colour swatch",
        kind="color",
        bounds=Rect(x=10, y=10, width=12, height=12),
        observation_id="obs-1",
        source="vision",
        confidence=0.95,
    )
    registry = TargetDetector().detect(
        observation, additional_targets=[visual_target]
    )
    assert registry.resolve(
        "paint.color.red", observation_id="obs-1"
    ).source == "vision"



def test_target_detector_runs_configured_visual_detectors():
    observation = Observation(observation_id="obs-visual", platform="windows")
    target = UITarget(
        target_id="paint.color.red",
        label="Red swatch",
        kind="color",
        bounds=Rect(x=12, y=20, width=16, height=16),
        observation_id="obs-visual",
        source="vision",
        confidence=0.9,
    )
    detector = TargetDetector(
        visual_detectors=[lambda current: [target] if current.observation_id == "obs-visual" else []]
    )
    registry = detector.detect(observation)
    assert registry.resolve("paint.color.red", observation_id="obs-visual") == target
