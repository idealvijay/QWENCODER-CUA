from pydantic import BaseModel


class WindowInfo(BaseModel):
    id: str
    title: str = ""
    process_id: int | None = None
    process_name: str | None = None
    visible: bool = True
    minimized: bool = False
    bounds: tuple[int, int, int, int] | None = None
    is_active: bool = False
