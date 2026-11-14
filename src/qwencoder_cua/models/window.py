from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class WindowInfo(BaseModel):
    id: str
    title: str = ""
    process_id: int | None = None
    process_name: str | None = None
    visible: bool = True
    minimized: bool = False
    bounds: tuple[int, int, int, int] | None = None
    is_active: bool = False


class WindowSelector(BaseModel):
    """Unambiguous selector used to bind a task to one desktop application window."""

    model_config = ConfigDict(frozen=True)

    window_id: str | None = None
    process_name: str | None = None
    title_contains: str | None = None

    @model_validator(mode="after")
    def validate_selector(self):
        if not any((self.window_id, self.process_name, self.title_contains)):
            raise ValueError(
                "WindowSelector requires at least one of window_id, process_name or title_contains."
            )
        for field_name in ("window_id", "process_name", "title_contains"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must not be blank.")
        return self

    def matches(self, window: WindowInfo) -> bool:
        if self.window_id is not None and window.id != self.window_id:
            return False
        if self.process_name is not None:
            if (window.process_name or "").casefold() != self.process_name.casefold():
                return False
        if self.title_contains is not None:
            if self.title_contains.casefold() not in (window.title or "").casefold():
                return False
        return True
