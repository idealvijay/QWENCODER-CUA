from datetime import datetime, timezone
from pydantic import BaseModel, Field
from .element import UIElement
from .window import WindowInfo

class ScreenshotRef(BaseModel):
    path: str | None = None
    media_type: str = "image/png"
    width: int | None = None
    height: int | None = None

class Observation(BaseModel):
    observation_id: str
    platform: str
    session_type: str | None = None
    active_window: WindowInfo | None = None
    windows: list[WindowInfo] = Field(default_factory=list)
    elements: list[UIElement] = Field(default_factory=list)
    accessibility_available: bool = False
    screenshot: ScreenshotRef | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: list[str] = Field(default_factory=list)
