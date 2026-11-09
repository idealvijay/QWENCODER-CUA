from __future__ import annotations
import os
import shutil
import subprocess
from dataclasses import dataclass

@dataclass
class PortalReadiness:
    session_type: str
    portal_bus_reachable: bool
    screencast_interface: bool
    remote_desktop_interface: bool
    pipewire_available: bool
    details: list[str]

def probe_wayland_portals(timeout: float = 2.0) -> PortalReadiness:
    """Read-only readiness probe; does not request portal consent or start streams."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    details: list[str] = []
    interfaces: set[str] = set()
    bus_ok = False
    if shutil.which("gdbus"):
        try:
            result = subprocess.run(
                ["gdbus", "introspect", "--session", "--dest",
                 "org.freedesktop.portal.Desktop", "--object-path",
                 "/org/freedesktop/portal/desktop"],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            bus_ok = result.returncode == 0
            if bus_ok:
                if "org.freedesktop.portal.ScreenCast" in result.stdout:
                    interfaces.add("screencast")
                if "org.freedesktop.portal.RemoteDesktop" in result.stdout:
                    interfaces.add("remote")
            else:
                details.append((result.stderr or result.stdout or "Portal introspection failed.").strip())
        except (OSError, subprocess.TimeoutExpired) as exc:
            details.append(f"Portal probe failed: {exc}")
    else:
        details.append("gdbus is unavailable; install GLib command-line tools.")
    pipewire = bool(shutil.which("pw-cli") or shutil.which("pipewire"))
    if not pipewire:
        details.append("PipeWire runtime/tooling was not detected.")
    if bus_ok:
        details.append("Portal is reachable; actual capture/input still requires interactive user consent.")
    return PortalReadiness(session or "unknown", bus_ok, "screencast" in interfaces,
                           "remote" in interfaces, pipewire, details)
