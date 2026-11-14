from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from types import SimpleNamespace

from PIL import Image

from qwencoder_cua.core.computer import Computer
from qwencoder_cua.drivers.cua.backend import CuaDriverBackend
from qwencoder_cua.models.selector import ElementSelector
from qwencoder_cua.models.window import WindowSelector


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (96, 64), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FakeWindowTarget:
    pid: int
    window_id: int


@dataclass
class FakeDesktopTarget:
    display_id: str


@dataclass
class FakeCoordinates:
    x: float
    y: float


@dataclass
class FakeElementPosition:
    element_token: str


@dataclass
class FakeClickInput:
    target: object
    position: object
    delivery_mode: object
    session: object
    button: object
    count: object


@dataclass
class FakeDragInput:
    from_x: float
    from_y: float
    to_x: float
    to_y: float
    target: object
    scope: object
    session: object
    duration_ms: int
    steps: int
    button: object
    modifier: object


@dataclass
class FakeGetWindowStateInput:
    pid: int
    window_id: int
    session: object
    query: object
    include_accessibility_tree: bool
    include_screenshot: bool
    screenshot_out_file: str | None
    max_elements: int
    max_depth: int
    max_dimension: object
    max_image_dimension: int


class FakeRuntime:
    def __init__(self):
        self.click_requests = []
        self.drag_requests = []
        self.window_state_requests = []
        self.closed = False

    async def list_apps(self, _request):
        return SimpleNamespace(apps=[
            SimpleNamespace(
                pid=12345,
                name="Microsoft Paint",
                running=True,
                active=True,
                launch_path=r"C:\Windows\System32\mspaint.exe",
            )
        ])

    async def list_windows(self, _request):
        return SimpleNamespace(windows=[
            SimpleNamespace(
                window_id=77,
                pid=12345,
                app_name="mspaint.exe",
                title="Untitled - Paint",
                bounds=SimpleNamespace(x=100, y=200, width=98, height=66),
                is_on_screen=True,
                z_index=5,
                minimized=False,
            )
        ])

    async def get_window_state(self, request):
        self.window_state_requests.append(request)
        image_bytes = _png_bytes()
        if request.screenshot_out_file:
            Image.open(io.BytesIO(image_bytes)).save(request.screenshot_out_file)
            images = []
        else:
            images = [
                SimpleNamespace(
                    mime_type="image/png",
                    data_base64=base64.b64encode(image_bytes).decode("ascii"),
                )
            ]
        element = SimpleNamespace(
            element_index=0,
            role="Button",
            depth=1,
            element_token="snapshot-1:0",
            label="Ellipse/Oval",
            value=None,
            value_description=None,
            enabled=True,
            selected=False,
            in_web_content=False,
            actions=["invoke"],
            parent_index=None,
            frame=SimpleNamespace(x=110, y=220, w=16, h=12),
            min=None,
            max=None,
        )
        return SimpleNamespace(
            pid=12345,
            window_id=77,
            snapshot_id="snapshot-1",
            app_name="mspaint.exe",
            window_title="Untitled - Paint",
            elements=[element],
            elements_complete=True,
            degraded=False,
            truncated=False,
            screenshot_width=96,
            screenshot_height=64,
            screenshot_scale=1.0,
            screenshot_frame_valid=True,
            window_bounds=SimpleNamespace(x=100, y=200, width=98, height=66),
            images=images,
        )

    async def click(self, request):
        self.click_requests.append(request)
        return SimpleNamespace(
            effect=SimpleNamespace(name="CONFIRMED"),
            summary="Cua Driver delivered the click.",
            hint=None,
            is_error=False,
            text="",
        )

    async def drag(self, request):
        self.drag_requests.append(request)
        return SimpleNamespace(is_error=False, text="drag delivered")

    async def move_cursor(self, _request):
        return SimpleNamespace(is_error=False, text="moved")

    async def get_desktop_state(self, _request):
        image_bytes = _png_bytes()
        return SimpleNamespace(
            is_error=False,
            text="desktop",
            images=[SimpleNamespace(data_base64=base64.b64encode(image_bytes).decode("ascii"))],
        )

    async def type_text(self, _request):
        return SimpleNamespace(is_error=False, text="typed")

    async def press_key(self, _request):
        return SimpleNamespace(is_error=False, text="pressed")

    async def scroll(self, _request):
        return SimpleNamespace(is_error=False, text="scrolled")

    async def shutdown(self):
        self.closed = True


class FakeSdk:
    class CuaDriver:
        runtime = None

        @classmethod
        def create(cls):
            cls.runtime = FakeRuntime()
            return cls.runtime

    ListAppsInput = lambda: SimpleNamespace()
    ListWindowsInput = lambda **kwargs: SimpleNamespace(**kwargs)
    GetWindowStateInput = FakeGetWindowStateInput
    GetDesktopStateInput = lambda **kwargs: SimpleNamespace(**kwargs)

    class ActionTarget:
        WINDOW = FakeWindowTarget
        DESKTOP = FakeDesktopTarget

    class ClickPosition:
        COORDINATES = FakeCoordinates
        ELEMENT = FakeElementPosition

    class InputDeliveryMode:
        BACKGROUND = "background"
        FOREGROUND = "foreground"

    class ClickButton:
        LEFT = "left"
        RIGHT = "right"
        MIDDLE = "middle"

    ClickInput = FakeClickInput
    DragInput = FakeDragInput

    class MoveCursorInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class TypeTextInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class PressKeyInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ScrollDirection:
        UP = "up"
        DOWN = "down"
        LEFT = "left"
        RIGHT = "right"

    class ScrollBy:
        LINE = "line"

    class ScrollInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


def _backend(monkeypatch):
    fake_sdk = FakeSdk()
    monkeypatch.setattr(
        "qwencoder_cua.drivers.cua.backend.importlib.import_module",
        lambda _name: fake_sdk,
    )
    return CuaDriverBackend(), fake_sdk


def test_cua_backend_is_used_as_computer_driver_and_maps_window_tokens(monkeypatch, tmp_path):
    driver, sdk = _backend(monkeypatch)
    screenshot_path = tmp_path / "window.png"

    with Computer(
        driver=driver,
        target_window=WindowSelector(process_name="mspaint.exe"),
    ) as computer:
        observation = computer.observe(screenshot_path=screenshot_path)
        assert observation.target_window is not None
        assert observation.target_window.id == "77"
        assert observation.target_window.process_name == "mspaint.exe"
        assert observation.screenshot.coordinate_space == "window"
        assert (observation.screenshot.width, observation.screenshot.height) == (96, 64)
        assert screenshot_path.exists()

        ellipse = computer.find_element(
            ElementSelector(role="Button", name="Ellipse/Oval")
        )
        assert ellipse.id
        assert ellipse.name == "Ellipse/Oval"
        assert ellipse.actions == ["click"]

        # The public QWENCODER element token resolves to the original Cua token.
        computer.click_element(ellipse.id)
        request = sdk.CuaDriver.runtime.click_requests[-1]
        assert request.position.element_token == "snapshot-1:0"
        assert request.target.pid == 12345
        assert request.target.window_id == 77
        assert request.delivery_mode == "background"

    assert sdk.CuaDriver.runtime.closed


def test_cua_backend_uses_snapshot_local_coordinate_origin(monkeypatch):
    driver, _sdk = _backend(monkeypatch)

    with Computer(
        driver=driver,
        target_window=WindowSelector(process_name="mspaint.exe"),
    ) as computer:
        observation = computer.observe()
        ellipse = computer.find_element(
            ElementSelector(role="Button", name="Ellipse/Oval")
        )

        # The SDK reported screen-space frame (110, 220), while the captured
        # client image starts at (101, 201). Computer localizes to (9, 19).
        assert ellipse.bounds.x == 9
        assert ellipse.bounds.y == 19
        assert observation.screenshot.origin_x == 101
        assert observation.screenshot.origin_y == 201


def test_cua_backend_draw_path_uses_native_drag_operations(monkeypatch):
    driver, sdk = _backend(monkeypatch)
    driver.connect()
    try:
        driver.capture_window("77")
        driver.draw_path([(10, 10), (20, 20), (30, 10)], duration_seconds=0.4)
        calls = sdk.CuaDriver.runtime.drag_requests
        assert len(calls) == 2
        assert (calls[0].from_x, calls[0].from_y) == (10.0, 10.0)
        assert (calls[0].to_x, calls[0].to_y) == (20.0, 20.0)
        assert (calls[1].from_x, calls[1].from_y) == (20.0, 20.0)
        assert (calls[1].to_x, calls[1].to_y) == (30.0, 10.0)
    finally:
        driver.disconnect()


def test_cua_backend_does_not_import_optional_sdk_until_connect(monkeypatch):
    driver, _sdk = _backend(monkeypatch)
    assert driver._runtime is None
    driver.connect()
    assert driver._runtime is not None
    driver.disconnect()
