from __future__ import annotations

from collections.abc import Iterable

from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.perception.accessibility_detector import AccessibilityTargetDetector
from qwencoder_cua.perception.target_registry import TargetRegistry


class TargetDetector:
    """Build a target registry from accessibility and optional visual detections."""

    def __init__(self, accessibility_detector: AccessibilityTargetDetector | None = None):
        self.accessibility_detector = accessibility_detector or AccessibilityTargetDetector()

    def detect(
        self,
        observation: Observation,
        *,
        additional_targets: Iterable[UITarget] = (),
    ) -> TargetRegistry:
        targets = self.accessibility_detector.detect(observation)
        targets.extend(additional_targets)
        return TargetRegistry(observation.observation_id, targets)
