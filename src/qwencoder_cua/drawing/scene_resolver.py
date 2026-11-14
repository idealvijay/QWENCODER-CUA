from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from qwencoder_cua.models.geometry import Point, Rect
from qwencoder_cua.models.scene import NormalizedPoint, NormalizedRect, ScenePlan
from qwencoder_cua.models.target import UITarget


class CanvasRegion(BaseModel):
    """Canvas bounds resolved from one current screenshot observation."""

    model_config = ConfigDict(frozen=True)
    target_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    bounds: Rect

    def validate_observation(self, observation_id: str) -> None:
        if observation_id != self.observation_id:
            raise ValueError(
                "canvas region is stale; resolve the canvas again from the latest observation"
            )

    def to_screen(self, point: NormalizedPoint, *, observation_id: str) -> Point:
        self.validate_observation(observation_id)
        return Point(
            x=self.bounds.x + round(point.x * max(0, self.bounds.width - 1)),
            y=self.bounds.y + round(point.y * max(0, self.bounds.height - 1)),
        )

    def rect_to_screen(self, rect: NormalizedRect, *, observation_id: str) -> Rect:
        self.validate_observation(observation_id)
        left = self.bounds.x + round(rect.x * self.bounds.width)
        top = self.bounds.y + round(rect.y * self.bounds.height)
        right = self.bounds.x + round((rect.x + rect.width) * self.bounds.width)
        bottom = self.bounds.y + round((rect.y + rect.height) * self.bounds.height)
        return Rect(
            x=left,
            y=top,
            width=max(1, right - left),
            height=max(1, bottom - top),
        )


class ResolvedObject(BaseModel):
    model_config = ConfigDict(frozen=True)
    object_id: str
    name: str
    primitive: str
    bounds: Rect | None = None
    points: list[Point] = Field(default_factory=list)
    style: dict
    z_index: int
    closed: bool


class ResolvedScene(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str
    canvas_target_id: str
    observation_id: str
    canvas_bounds: Rect
    objects: list[ResolvedObject]


def canvas_from_target(target: UITarget) -> CanvasRegion:
    if target.kind != "canvas":
        raise ValueError(f"target {target.target_id!r} is not classified as a canvas")
    if not target.visible or not target.enabled:
        raise ValueError("canvas target must be visible and enabled")
    return CanvasRegion(
        target_id=target.target_id,
        observation_id=target.observation_id,
        bounds=target.bounds,
    )


def resolve_scene(
    scene: ScenePlan,
    canvas: CanvasRegion,
    *,
    observation_id: str,
) -> ResolvedScene:
    """Resolve normalized scene geometry to current desktop/screenshot pixels."""
    canvas.validate_observation(observation_id)
    if scene.canvas_target_id != canvas.target_id:
        raise ValueError(
            f"scene targets canvas {scene.canvas_target_id!r}, not {canvas.target_id!r}"
        )
    resolved: list[ResolvedObject] = []
    for item in scene.ordered_objects:
        bounds = (
            canvas.rect_to_screen(item.bounds, observation_id=observation_id)
            if item.bounds is not None else None
        )
        points = [
            canvas.to_screen(point, observation_id=observation_id)
            for point in item.points
        ]
        resolved.append(ResolvedObject(
            object_id=item.object_id,
            name=item.name,
            primitive=item.primitive,
            bounds=bounds,
            points=points,
            style=item.style.model_dump(),
            z_index=item.z_index,
            closed=item.closed,
        ))
    return ResolvedScene(
        title=scene.title,
        canvas_target_id=scene.canvas_target_id,
        observation_id=observation_id,
        canvas_bounds=canvas.bounds,
        objects=resolved,
    )
