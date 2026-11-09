from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskPolicy:
    """Hard limits applied independently of the planner's output."""

    max_steps: int = 15
    max_runtime_seconds: float = 120.0
    max_text_chars: int = 4000
    verification_poll_interval: float = 0.25
    allowed_actions: frozenset[str] = field(default_factory=lambda: frozenset({
        "click", "type_text", "press_key", "scroll",
        "click_element", "focus_element", "set_element_value",
        "move_mouse", "drag", "draw_path",
    }))
    max_path_points: int = 64
    max_draw_duration_seconds: float = 10.0

    def __post_init__(self):
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive")
        if self.max_text_chars < 1:
            raise ValueError("max_text_chars must be positive")
        if not 2 <= self.max_path_points <= 64:
            raise ValueError("max_path_points must be between 2 and 64")
        if not 0.05 <= self.max_draw_duration_seconds <= 10.0:
            raise ValueError("max_draw_duration_seconds must be between 0.05 and 10")
