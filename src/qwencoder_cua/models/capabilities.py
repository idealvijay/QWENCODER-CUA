from pydantic import BaseModel


class DriverCapabilities(BaseModel):
    screenshot: bool = False
    window_enumeration: bool = False
    window_focus: bool = False
    mouse_input: bool = False
    keyboard_input: bool = False
    accessibility: bool = False
    clipboard: bool = False
    multi_monitor: bool = False
    global_input: bool = False
    background_input: bool = False
