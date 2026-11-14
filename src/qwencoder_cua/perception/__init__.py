"""Perception and screenshot-scoped UI target grounding."""

from qwencoder_cua.perception.accessibility_detector import AccessibilityTargetDetector
from qwencoder_cua.perception.color_detector import ColorSwatchDetector
from qwencoder_cua.perception.target_detector import TargetDetector
from qwencoder_cua.perception.target_registry import TargetRegistry

__all__ = ["AccessibilityTargetDetector", "ColorSwatchDetector", "TargetDetector", "TargetRegistry"]
