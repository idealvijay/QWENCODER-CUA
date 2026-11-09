# QWENCODER CUA Driver

**Version 0.4.0** — local-first Python desktop automation for Windows and Linux.
Hybrid perception uses accessibility semantics when available and screenshots as a visual fallback.

## v0.4 highlights

- **Wayland portal backend:** starts an XDG RemoteDesktop session, requests monitor sharing through ScreenCast, and uses the restricted PipeWire FD returned by the portal.
- **Portal-based input:** keyboard and pointer events are sent only for device classes the user approved in the desktop consent dialog.
- **PipeWire screenshots:** GStreamer `pipewiresrc` captures a frame from the portal-authorized stream.
- **Closed-loop task runner:** observe → ask planner for one next action → act → verify → observe again.
- **Local Ollama planner:** structured one-step decisions, optional screenshot input, accessibility-tree context, and `OLLAMA_URL` / `MODEL` configuration.
- **Safety limits:** action allow-list, max steps/runtime/text size, mandatory postconditions, and per-step user approval for consequential actions.
- **Visual postconditions:** compare before/after screenshots using `screen_changed` when an accessible state assertion is unavailable.

## Platform status

| Capability | Windows 10/11 | Rocky Linux X11 | Rocky Linux Wayland |
|---|---:|---:|---:|
| Screenshot | Yes | Yes | Yes, with portal + GStreamer |
| Coordinate mouse / keyboard | Yes | XTest backend | Portal Notify methods, consent-gated |
| Accessibility tree | UI Automation | AT-SPI | AT-SPI, if exposed by the desktop/apps |
| Semantic click / value | UIA | AT-SPI | AT-SPI, when app supports it |
| Element re-identification | Yes | Yes | When AT-SPI tree is available |
| Task runner + verification | Yes | Yes | Yes, subject to granted portal capabilities |

Wayland does not use X11 injection as a fallback. The user can grant screen sharing without granting keyboard or pointer access; capabilities reflect the actual consent response. Window enumeration/focus is not implemented through the RemoteDesktop portal.

## Requirements and installation

Python 3.11+ and a logged-in interactive desktop session.

### Windows 10/11 — PowerShell

Open PowerShell, clone the repository, and install the Windows extras:

```powershell
git clone https://github.com/idealvijay/QWENCODER-CUA.git
cd QWENCODER-CUA

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[windows,dev]"

python scripts/doctor.py
pytest -q
```

If PowerShell blocks the virtual-environment activation script, allow scripts for this terminal only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Keep this PowerShell window open with `.venv` activated when running the CLI.

### Rocky Linux X11

```bash
sudo dnf install -y python3.11 python3.11-devel gcc libX11 libXtst
# Install distribution-provided AT-SPI bindings if available.
sudo dnf install -y at-spi2-core
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[linux,dev]"
python scripts/doctor.py
pytest -q
```

### Rocky Linux Wayland

Package names vary between Rocky releases and enabled repositories. Install the desktop portal, PipeWire, the GStreamer PipeWire source plugin, and GLib D-Bus tools from your distribution's supported repositories. Typical package names include:

```bash
sudo dnf install -y xdg-desktop-portal pipewire pipewire-utils   gstreamer1-tools gstreamer1-plugins-base gstreamer1-plugins-good   gstreamer1-plugin-pipewire
```

Then install the Python extra:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[wayland,dev]"
python scripts/doctor.py
pytest -q
```

The exact GStreamer PipeWire plugin package name can differ by repository. `gst-inspect-1.0 pipewiresrc` should succeed before using screen capture. If AT-SPI is wanted as well, install the distro's `pyatspi` binding and `at-spi2-core`.

## Wayland consent and runtime

Entering `with Computer() as cua` on a Wayland session starts the portal request. The desktop environment displays its own sharing dialog. The user chooses which monitor/window and input devices to grant. QWENCODER does not bypass or automate that dialog.

The driver requests pointer and keyboard devices plus one monitor stream. If input devices are declined but a screen stream is approved, screenshots remain available while the denied input methods raise an explicit error.

Capture is performed through GStreamer's PipeWire source using the portal-provided PipeWire remote FD and stream target. No unrestricted PipeWire daemon capture is used.

## Quick start: observe and act

```python
from qwencoder_cua import Computer, ElementSelector

with Computer() as cua:
    observation = cua.observe()
    print(observation.platform, observation.active_window)
    print("accessible elements:", len(observation.elements))

    save = cua.find_element(ElementSelector(
        role="button", name="Save", automation_id="saveBtn"
    ))
    outcome = cua.act_and_verify(
        save.id,
        "click",
        {"element_present": {"role": "text", "name": "Saved"}},
        timeout=4.0,
    )
    print(outcome.success, outcome.verified, outcome.verification)
```

## Closed-loop local agent

Install Ollama for your operating system and make sure its local server is running. The default planner model is `minicpm-v4.5:q4_0`, a vision-capable model that can receive the current desktop screenshot. `OLLAMA_URL` defaults to `http://127.0.0.1:11434`. The environment variables below apply to the current terminal session.

### Windows 10/11 — PowerShell

Run these commands in the same PowerShell window where the virtual environment is activated:

```powershell
ollama pull minicpm-v4.5:q4_0

$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:QWENCODER_CUA_MODEL = "minicpm-v4.5:q4_0"

# Confirm the driver and local dependencies
qwencoder-cua doctor
qwencoder-cua windows
qwencoder-cua screenshot --output .\desktop.png
qwencoder-cua inspect --max-depth 10

# Start with a small, non-destructive task in the foreground application
qwencoder-cua run-goal "Inspect the currently open application and identify its main window and visible controls. Do not change anything."
```

To try it with Paint or Photoshop, open the application yourself first, leave it in the foreground, then run `qwencoder-cua run-goal "…"`. QWENCODER CUA v0.4 does not launch applications on your behalf. It supports screenshot observation, UI Automation where exposed, mouse clicks, keyboard input, text entry and scrolling. It does **not** yet provide drag/brush-stroke actions or a dedicated art-generation workflow.

### Rocky Linux — Bash

```bash
ollama pull minicpm-v4.5:q4_0
export OLLAMA_URL=http://127.0.0.1:11434
export QWENCODER_CUA_MODEL=minicpm-v4.5:q4_0
qwencoder-cua doctor
qwencoder-cua run-goal "Open the settings window and locate the display scale option"
```

The planner returns one structured action at a time. The runner takes a fresh observation after the action, checks the requested postcondition, and only then asks the planner for the next step. Consequential steps marked `approval_required` prompt in the CLI and default to denied.

### Planner API

```python
from qwencoder_cua import Computer, OllamaTaskPlanner, TaskPolicy, TaskRunner

with Computer() as cua:
    result = TaskRunner(
        cua,
        TaskPolicy(max_steps=10, max_runtime_seconds=90),
    ).run(
        "Find the Save button and confirm the document is saved",
        OllamaTaskPlanner(),
    )
    print(result.success, result.status, result.message)
```

### Execute a reviewed JSON plan

```bash
qwencoder-cua run-plan ./my-plan.json --max-steps 8
```

Each plan step must declare an expected postcondition. Supported assertions:

```python
{"element_absent": {"role": "dialog", "name": "Confirm"}}
{"element_present": {"role": "text", "name": "Saved"}}
{"element_value": {"selector": {"role": "edit", "automation_id": "filename"}, "equals": "scene.usd"}}
{"active_window_title_contains": "Houdini"}
{"screen_changed": {"min_fraction": 0.01}}
```

`screen_changed` is a visual-difference signal, not proof of semantic success. Prefer accessible state assertions when the application exposes them.

## CLI

```bash
qwencoder-cua version
qwencoder-cua doctor
qwencoder-cua screenshot --output desktop.png
qwencoder-cua windows
qwencoder-cua inspect --max-depth 10
qwencoder-cua portal-status
qwencoder-cua run-plan ./my-plan.json
qwencoder-cua run-goal "Find the Save button"
```

## Safety model

- Local Ollama endpoint by default; no hosted model or remote control service is required.
- No shell, Python execution, app-launch, or arbitrary tool-call action exists in the task plan schema.
- The runner enforces action allow-lists, step/runtime/text limits, required postconditions, and explicit approval gates.
- Wayland input/capture uses only the session and device permissions granted by the desktop portal.
- UI labels, values, screenshots and model output are untrusted input. Never pass them to shell execution or privileged code.
