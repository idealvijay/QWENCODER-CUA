# QWENCODER CUA Driver

**Version 0.2.0** — local-first, Python-first desktop automation for Windows and Linux.
Hybrid strategy: accessibility semantics first, screenshot/coordinate interaction as fallback.

## What's new in v0.2

- Windows UI Automation adapter using `pywinauto` (`backend="uia"`).
- Linux AT-SPI adapter using `pyatspi` for accessible application trees.
- Unified `observe()` returns screenshot, active window, windows, and normalized UI elements.
- Observation-scoped element IDs with TTL; stale IDs fail closed and require a fresh observation.
- Semantic operations: `click_element`, `focus_element`, `set_element_value`.
- Graceful fallback: if the accessibility service or bindings are missing, visual screenshot/input still work.
- CLI `inspect` emits a JSON observation; `doctor` checks platform prerequisites.

## Platform support matrix

| Capability | Windows 10/11 | Rocky Linux X11 | Rocky Linux Wayland |
|---|---:|---:|---:|
| Screenshot | Yes | Yes | Not implemented |
| Window enumeration/focus | Yes | Yes (backend dependent) | Not implemented |
| Coordinate mouse/keyboard | Yes | Yes (XTest) | Not implemented |
| Accessibility tree | UIA | AT-SPI | AT-SPI tree may work; global input/capture not implemented |
| Semantic click/value | UIA | AT-SPI | Not guaranteed; no portal input implementation |

Wayland intentionally does not use X11 injection as a fallback. Portal capture/input require user consent and a separate adapter; they are a later milestone. AT-SPI availability depends on desktop environment, service state, and distro packaging.

## Requirements

- Python 3.11+
- Windows 10/11 or Rocky Linux with a logged-in graphical desktop.
- X11 on Linux for current screenshot and coordinate-input backend.
- AT-SPI service/bindings for Linux semantic element discovery.

## Windows installation (PowerShell)

```powershell
git clone <your-repository-url> QWENCODER-CUA
cd QWENCODER-CUA
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[windows,dev]"
python scripts/doctor.py
pytest -q
```

## Rocky Linux installation

Package names vary by Rocky release and enabled repositories. Start with:

```bash
sudo dnf install -y python3.11 python3.11-devel gcc libX11 libXtst
# AT-SPI packages (availability depends on enabled repos):
sudo dnf install -y at-spi2-core
# If available in your configured repositories:
sudo dnf install -y python3-pyatspi
```

Then:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[linux,dev]"
python scripts/doctor.py
pytest -q
```

If `python3-pyatspi` is unavailable, use the distribution's supported AT-SPI Python binding package or a desktop Python environment that can import `pyatspi`. Do not assume `pip install pyatspi` is supported.

## Quick start

```python
from qwencoder_cua import Computer

with Computer() as cua:
    obs = cua.observe()
    print(obs.platform, obs.active_window)
    print("accessible elements:", len(obs.elements))
    for element in obs.elements[:20]:
        print(element.id, element.role, element.name, element.bounds)
```

Semantic actions use IDs from the latest observation only:

```python
with Computer() as cua:
    obs = cua.observe()
    button = next(e for e in obs.elements if e.role in {"button"} and e.name == "OK")
    cua.click_element(button.id)
```

To set an editable field:

```python
field = next(e for e in obs.elements if e.role in {"edit", "entry", "text"})
cua.set_element_value(field.id, "hello")
```

Fallback to visual coordinates when the application exposes no accessibility metadata:

```python
cua.click(420, 280)
cua.type_text("hello")
cua.press_key("enter")
```

## CLI

```bash
qwencoder-cua version
qwencoder-cua doctor
qwencoder-cua screenshot --output desktop.png
qwencoder-cua windows
qwencoder-cua inspect --max-depth 10
```

## Architecture

- `models/`: typed contracts for observations, windows, geometry and UI elements.
- `core/`: platform driver protocol, registry and public facade.
- `accessibility/`: provider contract and expiring element token store.
- `drivers/windows/`: Win32 visual/input backend plus UIA accessibility provider.
- `drivers/linux/`: X11 visual/input backend plus AT-SPI provider.
- `execution/`: action policies and safety primitives.
- `tests/`: OS-independent contract and token lifecycle tests.

## Safety model

- Runs in the logged-in user's desktop session; no service/daemon or remote control server.
- Accessibility IDs are ephemeral and expire; re-observe before acting after UI changes.
- No hidden/background input is claimed.
- The library does not bypass OS permission prompts or Wayland consent boundaries.
- Coordinate and semantic actions are powerful: use only on machines and applications you are authorized to control.
