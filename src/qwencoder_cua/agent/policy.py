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
    }))

    def __post_init__(self):
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive")
        if self.max_text_chars < 1:
            raise ValueError("max_text_chars must be positive")
