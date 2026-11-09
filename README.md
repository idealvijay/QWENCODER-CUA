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

## Windows 10/11 — step-by-step first run (Command Prompt)

These steps use **Command Prompt (CMD)**, not PowerShell. Run them in the same CMD window, from the repository folder containing `pyproject.toml`.

### 1. Open the repository and activate the environment

If the repository is already on disk, change to its folder. Replace the example path with your own:

```cmd
cd /d H:\path\to\QWENCODER-CUA
dir pyproject.toml
```

The `dir` command should show `pyproject.toml`. Activate the environment:

```cmd
call .venv\Scripts\activate.bat
```

If `.venv` does not exist yet, create it and install the project:

```cmd
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[windows,dev]"
```

You should now see `(.venv)` at the start of the prompt.

### 2. Check Ollama (do not start a second server)

```cmd
ollama list
```

If `minicpm-v4.5:q4_0` is not listed, download it:

```cmd
ollama pull minicpm-v4.5:q4_0
```

Set the local endpoint and model for this CMD window:

```cmd
set "OLLAMA_URL=http://127.0.0.1:11434"
set "QWENCODER_CUA_MODEL=minicpm-v4.5:q4_0"
curl http://127.0.0.1:11434/api/tags
```

A JSON response listing models means Ollama is reachable. The Ollama Windows app normally runs its server in the background. If `ollama serve` says the address or port is already in use, another server is probably already listening; do not keep starting more copies. Check the API with the `curl` command above. If it does not respond, launch Ollama from the Windows Start menu and retry.

> **CMD and PowerShell use different syntax:** in CMD use `set "NAME=value"`; in PowerShell use `$env:NAME = "value"`. Do not mix the two.

### 3. Run the diagnostic

```cmd
qwencoder-cua doctor
```

The `doctor` command's repository-path fix is included in this pull request. If you are still using an older checkout and it reports that `scripts\doctor.py` cannot be found, run this temporary workaround from the repository root:

```cmd
python scripts\doctor.py
```

A healthy Windows setup should report `OK` for Python 3.11+, `win32gui`, `pywinauto`, `pyautogui`, `mss`, and the interactive Windows session.

### 4. Capture and validate a screenshot

```cmd
qwencoder-cua screenshot --output desktop.png
dir desktop.png
python -c "from PIL import Image; im=Image.open('desktop.png'); print('Format:', im.format, 'Size:', im.size); im.verify(); print('Image file is valid')"
```

To open it directly in Paint, bypassing the default Windows image viewer:

```cmd
mspaint "%CD%\desktop.png"
```

If Paint opens the image but double-clicking PNG or JPG files in File Explorer does not, the image itself may be fine while the default viewer or file association is broken. Open **Settings → Apps → Default apps**, search for `.png`, `.jpg`, and `.jpeg`, and assign them to Photos or Paint. You can also open **Settings → Apps → Installed apps → Microsoft Photos → Advanced options → Repair**. Try **Reset** only if Repair does not help.

### 5. Inspect the desktop

Open Paint, Photoshop, or another target application yourself and leave it in the foreground. Then run:

```cmd
qwencoder-cua windows
qwencoder-cua inspect --max-depth 10
```

`windows` lists visible windows. `inspect` captures the current desktop and prints accessibility information exposed by the foreground application.

### 6. Run a safe local-agent test

```cmd
qwencoder-cua run-goal "Describe the currently open application and identify its visible controls. Do not make any changes."
```

If the command cannot connect to Ollama, repeat the API check in Step 2. If the model is missing, repeat `ollama pull minicpm-v4.5:q4_0`.

**v0.4 limitations:** QWENCODER CUA can observe the screen and use supported mouse, keyboard, text, and accessibility actions. It does not yet provide dedicated drag-and-drop, continuous brush strokes, or artwork-generation actions. It also does not launch Paint or Photoshop automatically; open the target application before running a task.

---

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

For read-only goals such as "describe the currently open application", the planner should answer from the current screenshot and accessibility context without interacting with the desktop. Its answer is returned in the final result's `message` field.

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
