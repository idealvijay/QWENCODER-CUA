from pydantic import BaseModel, Field


class Point(BaseModel):
    x: int
    y: int


class Rect(BaseModel):
    x: int
    y: int
    width: int
    height: int


class DisplayInfo(BaseModel):
    id: str
    width: int
    height: int
    scale_factor: float = 1.0
    bounds: Rect
    is_primary: bool = False
