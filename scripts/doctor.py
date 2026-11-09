from __future__ import annotations
import importlib.util, os, platform, shutil, sys

def check(label, ok, detail=""):
    print(f"[{'OK' if ok else 'MISSING'}] {label}" + (f": {detail}" if detail else ""))

print(f"QWENCODER CUA doctor | Python {sys.version.split()[0]} | {platform.platform()}")
check("Python >= 3.11", sys.version_info >= (3, 11))
if platform.system() == "Windows":
    for mod in ("win32gui", "pywinauto", "pyautogui", "mss"):
        check(mod, importlib.util.find_spec(mod) is not None)
    check("interactive Windows session", os.environ.get("SESSIONNAME") is not None, os.environ.get("SESSIONNAME", "unknown"))
elif platform.system() == "Linux":
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    check("desktop session", session in ("x11", "wayland"), session)
    check("DISPLAY", bool(os.environ.get("DISPLAY")), os.environ.get("DISPLAY", "unset"))
    check("WAYLAND_DISPLAY", bool(os.environ.get("WAYLAND_DISPLAY")), os.environ.get("WAYLAND_DISPLAY", "unset"))
    check("python-xlib", importlib.util.find_spec("Xlib") is not None)
    check("pyatspi", importlib.util.find_spec("pyatspi") is not None, "AT-SPI needs distro bindings + at-spi2-core")
    check("xdotool", shutil.which("xdotool") is not None, "optional helper for diagnostics")
else:
    check("supported OS", False, platform.system())
