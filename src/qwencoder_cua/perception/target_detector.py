from __future__ import annotations

from collections.abc import Callable, Iterable

from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.target import UITarget
from qwencoder_cua.perception.accessibility_detector import AccessibilityTargetDetector
from qwencoder_cua.perception.target_registry import TargetRegistry


class TargetDetector:
    """Build a target registry from accessibility and optional visual detections."""

    def __init__(
        self,
        accessibility_detector: AccessibilityTargetDetector | None = None,
        visual_detectors: Iterable[Callable[[Observation], Iterable[UITarget]]] = (),
    ):
        self.accessibility_detector = accessibility_detector or AccessibilityTargetDetector()
        self.visual_detectors = tuple(visual_detectors)

    def detect(
        self,
        observation: Observation,
        *,
        additional_targets: Iterable[UITarget] = (),
    ) -> TargetRegistry:
        targets = self.accessibility_detector.detect(observation)
        for detector in self.visual_detectors:
            targets.extend(detector(observation))
        targets.extend(additional_targets)
        return TargetRegistry(observation.observation_id, targets)
