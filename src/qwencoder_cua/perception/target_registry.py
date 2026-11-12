from __future__ import annotations

from collections.abc import Iterable

from qwencoder_cua.core.target_errors import (
    AmbiguousTargetError,
    StaleTargetError,
    TargetNotFoundError,
)
from qwencoder_cua.models.target import TargetKind, UITarget


class TargetRegistry:
    """Registry of named targets detected in exactly one screenshot observation."""

    def __init__(self, observation_id: str, targets: Iterable[UITarget] = ()):
        if not observation_id:
            raise ValueError("observation_id must not be empty")
        self.observation_id = observation_id
        self._targets: dict[str, UITarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: UITarget) -> None:
        if target.observation_id != self.observation_id:
            raise StaleTargetError(
                f"Target {target.target_id!r} belongs to observation "
                f"{target.observation_id!r}, not {self.observation_id!r}."
            )
        if target.target_id in self._targets:
            raise AmbiguousTargetError(f"Duplicate target ID: {target.target_id!r}.")
        self._targets[target.target_id] = target

    def register_many(self, targets: Iterable[UITarget]) -> None:
        for target in targets:
            self.register(target)

    def resolve(
        self,
        target_id: str,
        *,
        observation_id: str,
        minimum_confidence: float = 0.65,
    ) -> UITarget:
        self._check_observation(observation_id)
        target = self._targets.get(target_id)
        if target is None:
            raise TargetNotFoundError(f"Target {target_id!r} is not in the current observation.")
        if not target.visible or not target.enabled:
            raise TargetNotFoundError(f"Target {target_id!r} is not visible and enabled.")
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if target.confidence < minimum_confidence:
            raise TargetNotFoundError(
                f"Target {target_id!r} confidence {target.confidence:.2f} is below "
                f"the required {minimum_confidence:.2f}."
            )
        return target

    def find(
        self,
        *,
        observation_id: str,
        label: str | None = None,
        kind: TargetKind | None = None,
    ) -> list[UITarget]:
        self._check_observation(observation_id)
        normalized = label.casefold() if label else None
        return [
            target for target in self._targets.values()
            if (kind is None or target.kind == kind)
            and (normalized is None or normalized in target.label.casefold())
            and target.visible
            and target.enabled
        ]

    def prompt_context(self, *, observation_id: str) -> list[dict]:
        """Return compact, JSON-ready target details for a vision planner prompt."""
        self._check_observation(observation_id)
        return [
            {
                "target_id": target.target_id,
                "label": target.label,
                "kind": target.kind,
                "bounds": target.bounds.model_dump(),
                "center": target.center.model_dump(),
                "confidence": target.confidence,
                "source": target.source,
                "enabled": target.enabled,
            }
            for target in self._targets.values()
            if target.visible and target.enabled
        ]

    def all(self, *, observation_id: str) -> list[UITarget]:
        self._check_observation(observation_id)
        return list(self._targets.values())

    def _check_observation(self, observation_id: str) -> None:
        if observation_id != self.observation_id:
            raise StaleTargetError(
                f"Registry belongs to observation {self.observation_id!r}; "
                f"received {observation_id!r}. Capture a fresh registry before acting."
            )
