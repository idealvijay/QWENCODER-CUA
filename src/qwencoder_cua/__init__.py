"""QWENCODER CUA public API."""
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.models.action import ActionOutcome
from qwencoder_cua.models.geometry import Point
from qwencoder_cua.agent import (
    OllamaTaskPlanner, TaskDecision, TaskPlan, TaskPolicy, TaskRunner, TaskStep,
)
from qwencoder_cua.drawing import (
    CanvasRegion, ResolvedScene, canvas_from_target, resolve_scene,
)
from qwencoder_cua.models.scene import (
    DrawingStyle, NormalizedPoint, NormalizedRect, SceneObject, ScenePlan,
)
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.models.window import WindowSelector
from qwencoder_cua.perception import (
    AccessibilityTargetDetector, ColorSwatchDetector, TargetDetector, TargetRegistry,
)

__version__ = "0.6.0"
__all__ = [
    "Computer", "ElementSelector", "ActionOutcome", "Point", "OllamaTaskPlanner", "WindowSelector",
    "TaskDecision", "TaskPlan", "TaskPolicy", "TaskRunner", "TaskStep",
    "UITarget", "TargetRegistry", "TargetDetector", "AccessibilityTargetDetector", "ColorSwatchDetector",
    "CanvasRegion", "ResolvedScene", "canvas_from_target", "resolve_scene",
    "DrawingStyle", "NormalizedPoint", "NormalizedRect", "SceneObject", "ScenePlan",
    "__version__",
]
