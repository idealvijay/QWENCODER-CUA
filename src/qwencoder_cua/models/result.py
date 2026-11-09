from enum import Enum
from pydantic import BaseModel


class ActionEffect(str, Enum):
    CONFIRMED = "confirmed"
    UNVERIFIABLE = "unverifiable"
    SUSPECTED_NOOP = "suspected_noop"
    PARTIAL = "partial"
    REFUSED = "refused"


class ActionResult(BaseModel):
    success: bool
    effect: ActionEffect
    action_id: str
    observation_id: str | None = None
    verified: bool = False
    message: str = ""
    error_code: str | None = None
