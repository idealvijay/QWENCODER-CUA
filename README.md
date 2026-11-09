# QWENCODER CUA Driver

A local-first, Python-first computer-use runtime for Windows and Rocky Linux.
The project separates platform drivers from orchestration and AI models.

## Current status

- Core typed contracts and driver registry: implemented.
- Windows screenshot, window enumeration, focus, mouse and keyboard: initial implementation.
- Linux X11 screenshot, window enumeration and XTest input: initial implementation.
- Linux Wayland: detection and explicit capability/permission scaffolding; portal capture/input adapters are not yet implemented.
- Accessibility: contract and capability placeholders; native adapters are next milestone.
- No LLM or network service is required.

## Requirements

- Python 3.11+
- Windows 10/11, or Rocky Linux with a graphical desktop session.
- On Linux, X11 support requires an accessible X server and `DISPLAY`.
- Wayland sessions are detected but global input/capture is not claimed to work yet.

## Install

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[windows,dev]"
python scripts/doctor.py
```

### Rocky Linux

Install system prerequisites (package names can vary by Rocky release and enabled repositories):

```bash
sudo dnf install -y python3.11 python3.11-devel gcc
# For X11 development/testing:
sudo dnf install -y libX11 libXtst
```

Then:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[linux,dev]"
python scripts/doctor.py
```

For GNOME Wayland, install/use the desktop's XDG Desktop Portal and PipeWire packages.
This initial release reports Wayland interaction as unsupported rather than attempting
unauthorized global input injection.

## Quick start

```python
from qwencoder_cua import Computer

with Computer() as computer:
    observation = computer.observe()
    print(observation.platform)
    print(observation.active_window)
    computer.screenshot("desktop.png")
```

Input example:

```python
from qwencoder_cua import Computer

with Computer() as computer:
    computer.click(400, 300)
    computer.type_text("Hello from QWENCODER")
```

Input actions affect the active interactive desktop. Use only on a machine/session you own
or are authorized to control. Avoid running unattended actions until the safety policy and
verification layers are completed.

## CLI

```bash
qwencoder-cua doctor
qwencoder-cua screenshot --output desktop.png
qwencoder-cua windows
```

## Architecture

- `models`: Pydantic contracts.
- `core`: driver protocol, registry and public facade.
- `drivers/windows`: Win32 + MSS adapter.
- `drivers/linux/x11`: X11 + XTest adapter.
- `drivers/linux/wayland`: explicit capability detection and unsupported-operation responses.
- `execution`: permission checks and action results.
- `tests`: OS-independent contract tests and backend smoke tests.

## Development

```bash
pytest
ruff check .
```

See `docs/architecture.md` and `docs/security.md`.
