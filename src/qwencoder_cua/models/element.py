from pydantic import BaseModel, Field
from .geometry import Rect

class UIElement(BaseModel):
    """Normalized accessibility element. IDs are observation-scoped, not durable selectors."""
    id: str
    role: str
    name: str | None = None
    value: str | None = None
    bounds: Rect | None = None
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    actions: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    native_id: str | None = None
    depth: int = 0
