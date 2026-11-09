from pydantic import BaseModel, ConfigDict

class ElementSelector(BaseModel):
    """Exact semantic hints for resolving a control after an observation refresh."""
    model_config = ConfigDict(extra="forbid")
    role: str | None = None
    name: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    value: str | None = None
    parent_name: str | None = None
    visible_only: bool = True
    enabled_only: bool = True

    def has_identity(self) -> bool:
        return any(getattr(self, key) is not None for key in
                   ("role", "name", "automation_id", "class_name", "value", "parent_name"))
