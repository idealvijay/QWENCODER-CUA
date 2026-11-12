from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qwencoder_cua.models.geometry import Point, Rect

TargetKind = Literal[
    "button", "tool", "shape", "color", "canvas", "menu", "field", "control", "unknown"
]
TargetSource = Literal["accessibility", "vision", "ocr", "manual"]


class UITarget(BaseModel):
    """A named screen target with geometry scoped to one observation."""

    model_config = ConfigDict(frozen=True)

    target_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=240)
    kind: TargetKind = "unknown"
    bounds: Rect
    observation_id: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: TargetSource
    enabled: bool = True
    visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.bounds.width <= 0 or self.bounds.height <= 0:
            raise ValueError("target bounds must have positive width and height")
        return self

    @property
    def center(self) -> Point:
        return Point(
            x=self.bounds.x + self.bounds.width // 2,
            y=self.bounds.y + self.bounds.height // 2,
        )
