from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NormalizedPoint(BaseModel):
    """A point expressed relative to a canvas: (0, 0) top-left, (1, 1) bottom-right."""

    model_config = ConfigDict(frozen=True)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class NormalizedRect(BaseModel):
    """A rectangle expressed as fractions of the canvas dimensions."""

    model_config = ConfigDict(frozen=True)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_inside_canvas(self):
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("normalized rectangle must fit inside the canvas")
        return self


class DrawingStyle(BaseModel):
    model_config = ConfigDict(frozen=True)
    stroke: str | None = "#000000"
    fill: str | None = None
    stroke_width: float = Field(default=1.0, ge=0.0, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)


PrimitiveKind = Literal["line", "ellipse", "rectangle", "polygon", "path"]


class SceneObject(BaseModel):
    """One independently ordered object in a normalized drawing scene."""

    model_config = ConfigDict(frozen=True)
    object_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    primitive: PrimitiveKind
    bounds: NormalizedRect | None = None
    points: list[NormalizedPoint] = Field(default_factory=list, max_length=512)
    style: DrawingStyle = Field(default_factory=DrawingStyle)
    z_index: int = 0
    closed: bool = False

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.primitive in {"ellipse", "rectangle"} and self.bounds is None:
            raise ValueError(f"{self.primitive} requires normalized bounds")
        if self.primitive in {"line", "polygon", "path"} and len(self.points) < 2:
            raise ValueError(f"{self.primitive} requires at least two normalized points")
        if self.primitive == "polygon" and len(self.points) < 3:
            raise ValueError("polygon requires at least three normalized points")
        return self


class ScenePlan(BaseModel):
    """Layered, canvas-independent artwork plan generated before UI execution."""

    model_config = ConfigDict(frozen=True)
    title: str = Field(min_length=1, max_length=240)
    canvas_target_id: str = Field(min_length=1, max_length=160)
    objects: list[SceneObject] = Field(min_length=1, max_length=512)

    @property
    def ordered_objects(self) -> list[SceneObject]:
        return sorted(self.objects, key=lambda item: item.z_index)
