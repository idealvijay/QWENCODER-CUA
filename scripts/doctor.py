from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys


def check(label, ok, detail=""):
    print(f"[{'OK' if ok else 'MISSING'}] {label}" + (f": {detail}" if detail else ""))


print(f"QWENCODER CUA doctor | Python {sys.version.split()[0]} | {platform.platform()}")
check("Python >= 3.11", sys.version_info >= (3, 11))

if platform.system() == "Windows":
    for mod in ("win32gui", "pywinauto", "pyautogui", "mss"):
        check(mod, importlib.util.find_spec(mod) is not None)
    check("interactive Windows session", os.environ.get("SESSIONNAME") is not None,
          os.environ.get("SESSIONNAME", "unknown"))
elif platform.system() == "Linux":
    session = os.environ.get("XDG_SESSION_TYPE", "unknown").lower()
    check("desktop session", session in ("x11", "wayland"), session)
    check("DISPLAY", bool(os.environ.get("DISPLAY")), os.environ.get("DISPLAY", "unset"))
    check("WAYLAND_DISPLAY", bool(os.environ.get("WAYLAND_DISPLAY")),
          os.environ.get("WAYLAND_DISPLAY", "unset"))
    check("python-xlib", importlib.util.find_spec("Xlib") is not None)
    check("pyatspi", importlib.util.find_spec("pyatspi") is not None,
          "AT-SPI needs distro bindings + at-spi2-core")
    check("dbus-next", importlib.util.find_spec("dbus_next") is not None,
          "Install with pip install -e '.[wayland]' for portal sessions")
    if session == "wayland":
        check("gdbus", shutil.which("gdbus") is not None)
        check("gst-launch-1.0", shutil.which("gst-launch-1.0") is not None,
              "GStreamer tools are required for PipeWire frame capture")
        check("gst-inspect-1.0", shutil.which("gst-inspect-1.0") is not None)
        if shutil.which("gst-inspect-1.0"):
            import subprocess
            result = subprocess.run(
                ["gst-inspect-1.0", "pipewiresrc"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            check("GStreamer PipeWire source", result.returncode == 0,
                  "Install the distro's GStreamer PipeWire plugin")
    check("xdotool", shutil.which("xdotool") is not None, "optional X11 diagnostic helper")
else:
    check("supported OS", False, platform.system())
