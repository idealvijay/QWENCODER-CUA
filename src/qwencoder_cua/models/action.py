from datetime import datetime, timezone
from pydantic import BaseModel, Field

class ActionOutcome(BaseModel):
    """Distinguishes provider invocation from observed application state."""
    action: str
    element_id: str
    success: bool
    verified: bool = False
    verification: str
    before_observation_id: str | None = None
    after_observation_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict = Field(default_factory=dict)
