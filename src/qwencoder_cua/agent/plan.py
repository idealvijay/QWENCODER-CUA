from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from qwencoder_cua.models.selector import ElementSelector

PlanAction = Literal[
    "click", "type_text", "press_key", "scroll",
    "click_element", "focus_element", "set_element_value",
]


class TaskStep(BaseModel):
    """One bounded desktop action with a required, machine-checkable postcondition."""

    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    action: PlanAction
    x: int | None = None
    y: int | None = None
    dx: int = 0
    dy: int = 0
    text: str | None = None
    key: str | None = None
    value: str | None = None
    selector: ElementSelector | None = None
    expected: dict = Field(min_length=1)
    approval_required: bool = False
    timeout_seconds: float = Field(default=4.0, gt=0, le=30)

    @model_validator(mode="after")
    def validate_action_arguments(self):
        if self.action == "click" and (self.x is None or self.y is None):
            raise ValueError("click requires x and y coordinates")
        if self.action == "scroll" and self.dx == 0 and self.dy == 0:
            raise ValueError("scroll requires a non-zero dx or dy")
        if self.action == "type_text" and self.text is None:
            raise ValueError("type_text requires text")
        if self.action == "press_key" and not self.key:
            raise ValueError("press_key requires key")
        if self.action in {"click_element", "focus_element", "set_element_value"} and self.selector is None:
            raise ValueError(f"{self.action} requires a semantic selector")
        if self.action == "set_element_value" and self.value is None:
            raise ValueError("set_element_value requires value")
        return self


class TaskDecision(BaseModel):
    """One planner decision in the closed-loop task runner."""

    model_config = ConfigDict(extra="forbid")
    done: bool = False
    success: bool = True
    reason: str = ""
    step: TaskStep | None = None

    @model_validator(mode="after")
    def validate_decision(self):
        if self.done and self.step is not None:
            raise ValueError("A completed decision cannot contain a step")
        if not self.done and self.step is None:
            raise ValueError("A non-completed decision must contain a step")
        return self


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str = Field(min_length=1, max_length=1000)
    steps: list[TaskStep] = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stop_on_failure: bool = True


class TaskStepResult(BaseModel):
    step_id: str
    action: str
    dispatched: bool
    verified: bool
    message: str
    before_observation_id: str | None = None
    after_observation_id: str | None = None


class TaskRunResult(BaseModel):
    plan_id: str
    goal: str
    success: bool
    status: Literal["completed", "failed", "approval_required", "timed_out"]
    steps: list[TaskStepResult] = Field(default_factory=list)
    message: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
