import os
import platform

from qwencoder_cua.core.exceptions import DriverUnavailableError


def detect_linux_session() -> str:
    """Return wayland, x11 or unknown. Prefer XDG_SESSION_TYPE over DISPLAY."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in {"wayland", "x11"}:
        return session
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def create_driver():
    system = platform.system()
    if system == "Windows":
        from qwencoder_cua.drivers.windows.backend import WindowsDriver
        return WindowsDriver()
    if system == "Linux":
        from qwencoder_cua.drivers.linux.backend import LinuxDriver
        return LinuxDriver(session_type=detect_linux_session())
    raise DriverUnavailableError(f"Unsupported operating system: {system}")
