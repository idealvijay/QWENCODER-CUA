from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from qwencoder_cua.core.driver import BaseDriver
from qwencoder_cua.core.exceptions import DriverUnavailableError, UnsupportedOperationError
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REMOTE_IFACE = "org.freedesktop.portal.RemoteDesktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"
EVDEV_BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}

KEYSYMS = {
    "enter": 0xFF0D, "return": 0xFF0D, "esc": 0xFF1B, "escape": 0xFF1B,
    "tab": 0xFF09, "backspace": 0xFF08, "delete": 0xFFFF, "space": 0x20,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "home": 0xFF50, "end": 0xFF57, "pageup": 0xFF55, "pagedown": 0xFF56,
    "insert": 0xFF63, "shift": 0xFFE1, "ctrl": 0xFFE3, "control": 0xFFE3,
    "alt": 0xFFE9, "super": 0xFFEB, "meta": 0xFFEB,
}
KEYSYMS.update({f"f{i}": 0xFFBD + i for i in range(1, 13)})


def _unwrap(value: Any) -> Any:
    """Remove dbus-next Variant wrappers from portal response values."""
    if hasattr(value, "value") and value.__class__.__name__ == "Variant":
        return _unwrap(value.value)
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_unwrap(item) for item in value)
    return value


class WaylandPortalDriver(BaseDriver):
    """Consent-based Wayland screen capture and input through XDG Desktop Portal.

    A RemoteDesktop session is created, the user is asked to approve keyboard,
    pointer and monitor sharing, and ScreenCast exposes a restricted PipeWire FD.
    Frames are decoded with the system GStreamer PipeWire source plugin.
    """

    name = "linux-wayland"

    def __init__(self, request_timeout: float = 120.0, capture_timeout: float = 12.0):
        self.request_timeout = request_timeout
        self.capture_timeout = capture_timeout
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._bus = None
        self._remote = None
        self._screencast = None
        self._session_handle = None
        self._pipewire_fd: int | None = None
        self._node_id: int | None = None
        self._pipewire_serial: str | None = None
        self._logical_size: tuple[int, int] | None = None
        self._pixel_size: tuple[int, int] | None = None
        self._keyboard_granted = False
        self._pointer_granted = False
        self._pending: dict[str, asyncio.Future] = {}
        self._message_handler = None
        self._connected = False

    @property
    def capabilities(self):
        return DriverCapabilities(
            screenshot=self._pipewire_fd is not None,
            window_enumeration=False,
            window_focus=False,
            mouse_input=self._pointer_granted,
            keyboard_input=self._keyboard_granted,
            clipboard=False,
            global_input=self._pointer_granted or self._keyboard_granted,
            background_input=False,
            accessibility=False,
            multi_monitor=False,
        )

    def connect(self):
        if os.name != "posix" or os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
            raise DriverUnavailableError("WaylandPortalDriver requires a Linux Wayland desktop session.")
        try:
            import dbus_next  # noqa: F401
        except ImportError as exc:
            raise DriverUnavailableError('Install the Wayland extra: pip install -e ".[wayland]"') from exc

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="qwencoder-wayland-portal", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise DriverUnavailableError("Could not start the Wayland portal event loop.")
        try:
            self._call(self._async_connect(), timeout=self.request_timeout + 15)
            self._connected = True
        except Exception:
            try:
                self._call(self._async_close_session(), timeout=5)
            except Exception:
                pass
            self._stop_loop()
            raise

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _call(self, coroutine, timeout=None):
        if self._loop is None or self._thread is None:
            raise RuntimeError("Wayland portal runtime is not running.")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout or self.request_timeout + 10)

    def _stop_loop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
        self._loop = None
        self._thread = None
        self._ready.clear()

    async def _async_connect(self):
        from dbus_next import Variant
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType, MessageType

        self._Variant = Variant
        self._MessageType = MessageType
        self._bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()
        introspection = await self._bus.introspect(PORTAL_BUS, PORTAL_PATH)
        proxy = self._bus.get_proxy_object(PORTAL_BUS, PORTAL_PATH, introspection)
        self._remote = proxy.get_interface(REMOTE_IFACE)
        self._screencast = proxy.get_interface(SCREENCAST_IFACE)

        def on_message(message):
            if (message.message_type == MessageType.SIGNAL
                    and message.interface == REQUEST_IFACE
                    and message.member == "Response"):
                future = self._pending.get(message.path)
                if future is not None and not future.done():
                    future.set_result((message.body[0], message.body[1]))
            return False

        self._message_handler = on_message
        self._bus.add_message_handler(on_message)

        session_token = f"qwcu_session_{uuid4().hex}"
        create_options = {"session_handle_token": Variant("s", session_token)}
        created = await self._portal_request(
            self._remote.call_create_session, create_options, "create"
        )
        self._session_handle = _unwrap(created.get("session_handle"))
        if not self._session_handle:
            raise DriverUnavailableError("The portal did not return a RemoteDesktop session handle.")

        # Ask only for pointer + keyboard. The portal itself presents the consent UI.
        await self._portal_request(
            self._remote.call_select_devices,
            {"types": Variant("u", 1 | 2)},
            "devices",
            self._session_handle,
        )

        # Request one monitor stream. ScreenCast is intentionally joined to the
        # RemoteDesktop session so a single user consent flow authorizes both.
        await self._portal_request(
            self._screencast.call_select_sources,
            {"types": Variant("u", 1), "multiple": Variant("b", False)},
            "sources",
            self._session_handle,
        )

        started = await self._portal_request(
            self._remote.call_start, {}, "start", self._session_handle, ""
        )
        devices = int(_unwrap(started.get("devices", 0)))
        self._keyboard_granted = bool(devices & 1)
        self._pointer_granted = bool(devices & 2)
        streams = _unwrap(started.get("streams", []))
        if not streams:
            raise DriverUnavailableError(
                "The portal session was approved without a screen stream. Reconnect and select a monitor."
            )
        self._node_id, properties = streams[0]
        self._node_id = int(self._node_id)
        properties = _unwrap(properties)
        serial = properties.get("pipewire-serial")
        self._pipewire_serial = str(serial) if serial is not None else None
        size = properties.get("size") or properties.get("logical_size")
        if isinstance(size, (list, tuple)) and len(size) == 2:
            self._logical_size = (int(size[0]), int(size[1]))

        pipewire_fd = await self._screencast.call_open_pipe_wire_remote(
            self._session_handle, {}
        )
        if hasattr(pipewire_fd, "take"):
            self._pipewire_fd = pipewire_fd.take()
        else:
            self._pipewire_fd = int(pipewire_fd)

        # Screen capture remains useful when the user grants screen sharing but declines input.
        # The capability flags below expose exactly which input devices were approved.

    async def _portal_request(self, method, options, token_prefix, *args):
        """Subscribe to Request.Response before invoking the portal method (no lost-response race)."""
        token = f"qwcu_{token_prefix}_{uuid4().hex}"
        sender = (self._bus.unique_name or "").lstrip(":").replace(".", "_")
        expected_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        future = asyncio.get_running_loop().create_future()
        self._pending[expected_path] = future
        request_options = dict(options)
        request_options["handle_token"] = self._Variant("s", token)
        try:
            returned_path = await method(*args, request_options)
            if returned_path != expected_path:
                # Older portal versions may not implement predictable request paths.
                self._pending.pop(expected_path, None)
                self._pending[returned_path] = future
            response, results = await asyncio.wait_for(future, timeout=self.request_timeout)
        except asyncio.TimeoutError as exc:
            raise DriverUnavailableError(
                "Timed out waiting for the desktop portal. Check the desktop consent dialog."
            ) from exc
        finally:
            self._pending.pop(expected_path, None)
            if "returned_path" in locals():
                self._pending.pop(returned_path, None)
        if int(response) != 0:
            reason = "cancelled by the user" if int(response) == 1 else "ended without approval"
            raise DriverUnavailableError(f"Desktop portal request was {reason}.")
        return _unwrap(results)

    def disconnect(self):
        try:
            if self._loop is not None and self._session_handle:
                self._call(self._async_close_session(), timeout=5)
        except Exception:
            pass
        if self._pipewire_fd is not None:
            try:
                os.close(self._pipewire_fd)
            except OSError:
                pass
            self._pipewire_fd = None
        self._stop_loop()
        self._connected = False
        self._session_handle = None
        self._node_id = None
        self._keyboard_granted = False
        self._pointer_granted = False

    async def _async_close_session(self):
        if self._bus is None:
            return
        if self._session_handle:
            try:
                introspection = await self._bus.introspect(PORTAL_BUS, self._session_handle)
                proxy = self._bus.get_proxy_object(PORTAL_BUS, self._session_handle, introspection)
                session = proxy.get_interface(SESSION_IFACE)
                await session.call_close()
            except Exception:
                pass
        try:
            self._bus.disconnect()
        except Exception:
            pass
        self._bus = None

    def _check(self):
        if not self._connected or self._loop is None:
            raise RuntimeError("Wayland portal driver is not connected.")

    def screenshot(self, output: str | Path | None = None):
        self._check()
        if self._pipewire_fd is None or self._node_id is None:
            raise DriverUnavailableError("No approved PipeWire screen stream is active.")
        gst = shutil.which("gst-launch-1.0")
        if not gst:
            raise DriverUnavailableError(
                "Screen capture needs GStreamer with the PipeWire plugin. Install "
                "gstreamer1-tools, gstreamer1-plugins-good and gstreamer1-plugin-pipewire."
            )
        if output:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
        else:
            temp_fd, temp_name = tempfile.mkstemp(suffix=".png")
            os.close(temp_fd)
            destination = Path(temp_name)
        fd = os.dup(self._pipewire_fd)
        source_args = [f"fd={fd}"]
        if self._pipewire_serial:
            source_args.append(f"target-object={self._pipewire_serial}")
        else:
            source_args.append(f"path={self._node_id}")
        command = [
            gst, "-q", "pipewiresrc", *source_args, "num-buffers=1",
            "!", "videoconvert", "!", "pngenc", "!", "filesink", f"location={destination}",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=self.capture_timeout, pass_fds=(fd,), check=False,
            )
            if result.returncode != 0:
                raise DriverUnavailableError(
                    "GStreamer could not read the approved PipeWire stream: "
                    + (result.stderr.strip() or result.stdout.strip())
                )
            with Image.open(destination) as captured:
                image = captured.convert("RGB")
            self._pixel_size = image.size
            if output:
                image.save(output)
            return image
        except subprocess.TimeoutExpired as exc:
            raise DriverUnavailableError("Timed out waiting for a PipeWire video frame.") from exc
        finally:
            os.close(fd)
            if output is None:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass

    def get_windows(self) -> list[WindowInfo]:
        self._check()
        return []

    def get_active_window(self) -> WindowInfo | None:
        self._check()
        return None

    def focus_window(self, window_id: str):
        raise UnsupportedOperationError("Wayland portal sessions do not expose global window focusing.")

    def _notify(self, method_name: str, *args):
        self._check()
        if not self._session_handle:
            raise RuntimeError("No approved RemoteDesktop session.")
        method = getattr(self._remote, method_name)
        return self._call(method(self._session_handle, {}, *args), timeout=5)

    def move(self, x: int, y: int):
        if not self._pointer_granted:
            raise UnsupportedOperationError("The user did not grant pointer control in the portal dialog.")
        logical_x, logical_y = float(x), float(y)
        if self._logical_size and self._pixel_size:
            logical_x *= self._logical_size[0] / max(1, self._pixel_size[0])
            logical_y *= self._logical_size[1] / max(1, self._pixel_size[1])
        self._notify("call_notify_pointer_motion_absolute", self._node_id, logical_x, logical_y)

    def mouse_down(self, x: int, y: int, button: str = "left"):
        if button not in EVDEV_BUTTONS:
            raise ValueError(f"Unsupported mouse button: {button}")
        if not self._pointer_granted:
            raise UnsupportedOperationError("The user did not grant pointer control in the portal dialog.")
        self.move(x, y)
        self._notify("call_notify_pointer_button", EVDEV_BUTTONS[button], 1)

    def mouse_up(self, button: str = "left"):
        if button not in EVDEV_BUTTONS:
            raise ValueError(f"Unsupported mouse button: {button}")
        if not self._pointer_granted:
            raise UnsupportedOperationError("The user did not grant pointer control in the portal dialog.")
        self._notify("call_notify_pointer_button", EVDEV_BUTTONS[button], 0)

    def click(self, x: int, y: int, button: str = "left"):
        self.mouse_down(x, y, button)
        try:
            pass
        finally:
            self.mouse_up(button)

    def scroll(self, dx=0, dy=0):
        if not self._pointer_granted:
            raise UnsupportedOperationError("The user did not grant pointer control in the portal dialog.")
        self._notify("call_notify_pointer_axis", float(dx), float(dy))

    @staticmethod
    def _keysym(key: str) -> int:
        normalized = key.strip().lower()
        if normalized in KEYSYMS:
            return KEYSYMS[normalized]
        if len(key) == 1:
            codepoint = ord(key)
            return codepoint if codepoint < 0x100 else 0x01000000 | codepoint
        raise ValueError(f"Unsupported Wayland key name: {key}")

    def _key_event(self, keysym: int, pressed: bool):
        self._notify("call_notify_keyboard_keysym", keysym, 1 if pressed else 0)

    def press_key(self, key: str):
        if not self._keyboard_granted:
            raise UnsupportedOperationError("The user did not grant keyboard control in the portal dialog.")
        parts = [part.strip() for part in key.split("+") if part.strip()]
        if not parts:
            raise ValueError("Key must not be empty.")
        symbols = [self._keysym(part) for part in parts]
        for symbol in symbols:
            self._key_event(symbol, True)
        for symbol in reversed(symbols):
            self._key_event(symbol, False)

    def type_text(self, text: str):
        if not self._keyboard_granted:
            raise UnsupportedOperationError("The user did not grant keyboard control in the portal dialog.")
        for char in text:
            if char == "\n":
                self.press_key("enter")
            elif char == "\t":
                self.press_key("tab")
            elif char == "\r":
                continue
            elif char.isupper() and char.isascii():
                shift = KEYSYMS["shift"]
                self._key_event(shift, True)
                self._key_event(ord(char.lower()), True)
                self._key_event(ord(char.lower()), False)
                self._key_event(shift, False)
            else:
                symbol = self._keysym(char)
                self._key_event(symbol, True)
                self._key_event(symbol, False)
