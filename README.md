# QWENCODER CUA Driver

**Version 0.7.0** — local-first Python desktop automation for Windows and Linux.
Hybrid perception uses accessibility semantics when available and screenshots as a visual fallback.

## v0.5 highlights

- **Wayland portal backend:** starts an XDG RemoteDesktop session, requests monitor sharing through ScreenCast, and uses the restricted PipeWire FD returned by the portal.
- **Portal-based input:** keyboard and pointer events are sent only for device classes the user approved in the desktop consent dialog.
- **PipeWire screenshots:** GStreamer `pipewiresrc` captures a frame from the portal-authorized stream.
- **Closed-loop task runner:** observe → ask planner for one next action → act → verify → observe again.
- **Local Ollama planner:** structured one-step decisions, optional screenshot input, accessibility-tree context, and `OLLAMA_URL` / `MODEL` configuration.
- **Safety limits:** action allow-list, max steps/runtime/text size, mandatory postconditions, and per-step user approval for consequential actions.
- **Visual postconditions:** compare before/after screenshots using `screen_changed` when an accessible state assertion is unavailable.
- **Creative pointer input:** held-button mouse input, straight-line drags and sampled multi-waypoint paths on Windows, Linux X11 and consent-approved Linux Wayland sessions.
- **Atomic strokes:** each drag/path attempts to release the pointer button even when movement fails.
- **Bounded drawing plans:** waypoint count, duration and screenshot-coordinate bounds are validated before input is sent.
- **Shape path helpers:** generate circle and rectangle polylines for drawing with the currently selected application tool.
- **Named UI target registry:** assign semantic IDs to visible accessibility targets, retain their bounds/confidence/source, and reject stale screenshot targets.
- **Named target actions:** MiniCPM can request `click_target` by ID; the runner resolves the target again from a fresh pre-click observation.
- **Canvas-relative scene model:** describe layered artwork using normalized geometry independent of desktop resolution and window position.
- **Deterministic geometry:** generate smooth ellipse, cubic Bezier and polygon paths; resolve scene objects against the current canvas bounds.
- **Palette swatch detector:** locate a requested colour only within an explicitly supplied palette region, avoiding guesses across the whole desktop.
- **Ollama scene planner:** convert a natural-language artwork brief into a schema-validated normalized ScenePlan.
- **Verified drawing executor:** render supported scene objects as bounded paths, re-detecting the canvas and verifying every stroke.

## Platform status

| Capability | Windows 10/11 | Rocky Linux X11 | Rocky Linux Wayland |
|---|---:|---:|---:|
| Screenshot | Yes | Yes | Yes, with portal + GStreamer |
| Coordinate mouse / keyboard | Yes | XTest backend | Portal Notify methods, consent-gated |
| Held mouse / drag / draw path | Yes | XTest backend | Portal pointer consent required |
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
set "QWENCODER_CUA_NUM_CTX=20480"
curl http://127.0.0.1:11434/api/tags
```

A JSON response listing models means Ollama is reachable. The Ollama Windows app normally runs its server in the background. If `ollama serve` says the address or port is already in use, another server is probably already listening; do not keep starting more copies. Check the API with the `curl` command above. If it does not respond, launch Ollama from the Windows Start menu and retry.

> **CMD and PowerShell use different syntax:** in CMD use `set "NAME=value"`; in PowerShell use `$env:NAME = "value"`. Do not mix the two.

The planner sends this context size to Ollama through `options.num_ctx`. The default is `20480` tokens so screenshot + UI context can exceed Ollama's 4096-token default. Override it with `QWENCODER_CUA_NUM_CTX` if needed. MiniCPM-V 4.5 Q4_0 is listed with a 40K context window; actual speed and memory use depend on your hardware and Ollama configuration.

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

Open Paint, Photoshop, or another target application yourself. The application must be in the foreground when QWENCODER captures the observation. You can inspect the current windows and active accessibility tree with:

```cmd
qwencoder-cua windows
qwencoder-cua inspect --max-depth 10
```

`windows` lists visible windows. `inspect` captures the current desktop and prints accessibility information exposed by the foreground application. The current v0.4 agent does not have a window-switch action, so it cannot activate Paint from inside the task plan.

**Tip — start an observation without leaving the target app covered by CMD:** first open Paint. Then, from CMD, run this background command:

```cmd
start "QWENCODER Paint observer" /min cmd /c "timeout /t 7 /nobreak >nul & qwencoder-cua run-goal ""Describe the Paint interface, canvas, ribbon tools, drawing controls and visible options. Do not make any changes."" > paint-observation.txt 2>&1"
```

Immediately press **Alt+Tab** to bring Paint to the foreground. Keep Paint visible while QWENCODER runs. When it finishes, return to CMD and read the result:

```cmd
type paint-observation.txt
```

If the result says the active application is still `cmd.exe`, Paint was not foreground when the observation was taken; repeat the background command and switch to Paint during the seven-second countdown.

### 6. Run a safe local-agent test

```cmd
qwencoder-cua run-goal "Describe the currently open application and identify its visible controls. Do not make any changes."
```

If the command cannot connect to Ollama, repeat the API check in Step 2. If the model is missing, repeat `ollama pull minicpm-v4.5:q4_0`.

If QWENCODER reports `HTTP 400 Bad Request`, the Ollama server was reached but rejected the request. Check that the configured model exists and supports images:

```cmd
ollama list
ollama show minicpm-v4.5:q4_0
```

The application will show Ollama's detailed HTTP error after the HTTP-error diagnostic fix is installed. Use that message to distinguish an unsupported request, image-processing issue, or model/runtime problem; do not treat every HTTP 400 as a connection failure.

**Current limitations:** QWENCODER CUA does not yet provide native PSD layer/object editing, application-specific document APIs, or image-generation models. Generic drags and brush strokes are now available. It also does not launch Paint or Photoshop automatically; open the target application before running a task.

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

## Creative input: drawing paths and strokes

QWENCODER CUA 0.5 adds low-level, application-independent drawing primitives. These send pointer events to the **currently focused application**; they do not select a Paint/Photoshop brush or colour automatically. Select the desired tool and colour in the target application first, and use coordinates measured from the desktop screenshot. The direct Python `Computer` API accepts native desktop screenshot pixels.

### Python API

```python
from qwencoder_cua import Computer
from qwencoder_cua.creative import circle_path, rectangle_path

with Computer() as cua:
    observation = cua.observe()
    print("Desktop size:", observation.screenshot.width, observation.screenshot.height)

    # Example coordinates only: replace these with positions inside your canvas.
    cua.draw_path(
        circle_path(center_x=900, center_y=500, radius=90, segments=48),
        button="left",
        duration_seconds=1.5,
    )

    cua.draw_path(
        rectangle_path(left=700, top=350, width=240, height=160),
        duration_seconds=1.0,
    )
```

The lower-level `Computer` methods are `move(x, y)`, `mouse_down(x, y, button)`, `mouse_up(button)`, `drag(start_x, start_y, end_x, end_y, ...)` and `draw_path(points, ...)`. Prefer `drag` or `draw_path` for planned strokes: they perform press/move/release as one operation, and the shared path executor releases the button in a `finally` block.

### Local agent drawing actions

The Ollama planner may emit `move_mouse`, `drag` or `draw_path` steps. Planner-produced click and drawing coordinates are measured in the resized image shown to the vision model; the runner maps them to full desktop pixels before dispatch. A path contains 2–64 waypoints, and its duration is limited to 10 seconds. QWENCODER validates against the planner image dimensions. The direct Python `Computer` drawing API uses native desktop screenshot pixels. A path should use a `screen_changed` postcondition (for example, `{"screen_changed": {"min_fraction": 0.001}}`) so the runner checks whether the canvas visibly changed.

Example request after opening Paint, selecting a brush and colour, and placing Paint in the foreground:

```cmd
qwencoder-cua run-goal "Draw a red circle near the centre of the blank Paint canvas. Use a smooth closed path and verify that the canvas changes."
```

For coordinate-driven UI selections and strokes, use a visual `screen_changed` postcondition rather than guessing that a colour swatch or tool control disappears after selection. The runner captures a fresh screenshot before every planned step and maps planner-image coordinates using that observation's current desktop width and height. The planner now checks each model-generated coordinate against the exact resized image dimensions before a step is accepted. If a coordinate is out of range, the model gets one correction attempt with the offending point and valid bounds; a second invalid answer is rejected without clicking. If the Windows display resolution or scaling changes between tasks, start a new task so the model receives the updated screenshot dimensions.

The agent is not Photoshop- or Paint-specific. It uses the visible interface to select tools where possible, then sends generic pointer paths. Layer management, native PSD object creation, text editing and app-specific shape APIs are not part of this first creative-input release. Use a test canvas or a new blank document first; generic pointer paths operate on the current foreground app and are not undo-aware.

---

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

To try it with Paint or Photoshop, open the application yourself first, leave it in the foreground, then run `qwencoder-cua run-goal "…"`. QWENCODER CUA v0.5 does not launch applications on your behalf. It supports screenshot observation, UI Automation where exposed, mouse clicks, keyboard input, text entry, scrolling, dragging and sampled drawing paths. It does not yet provide native PSD layer/object editing or image-generation models.

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
qwencoder-cua run-goal "Draw a red circle on the current canvas and verify the visible change"
```


## Target-window mode (Windows)

When a task is started from CMD or PowerShell, the console should not decide what the agent sees.
Pin the run to the target application instead. List windows and identify the process name or window ID:

```cmd
qwencoder-cua windows
qwencoder-cua screenshot --process-name mspaint.exe --output paint-window.png
qwencoder-cua run-goal "Draw a red circle on the canvas and verify the result" --process-name mspaint.exe
```

You can also narrow by a title fragment or an exact handle:

```cmd
qwencoder-cua run-goal "Describe this window" --window-title "Untitled - Paint"
qwencoder-cua run-goal "Describe this window" --window-id 123456
```

Target-window mode captures the selected window's client area, uses that window's UI Automation
tree, and re-focuses/re-resolves the target before every observation. Window-relative model
coordinates are translated using the current client-area screen origin before mouse input.
The target is selected once by process/title/handle; a recreated native window handle can be
re-resolved through the original process identity when unambiguous. Ambiguous matches are
rejected rather than guessed. If Windows blocks foreground activation, click the target app
once and rerun. This mode currently requires the Windows window-enumeration, focus and capture
backend; Linux Wayland portals do not expose target-window enumeration/focus in this release.

Without these flags, QWENCODER retains its existing full-desktop / foreground-window behavior.

## Safety model

- Local Ollama endpoint by default; no hosted model or remote control service is required.
- No shell, Python execution, app-launch, or arbitrary tool-call action exists in the task plan schema.
- The runner enforces action allow-lists, step/runtime/text limits, required postconditions, and explicit approval gates.
- Wayland input/capture uses only the session and device permissions granted by the desktop portal.
- UI labels, values, screenshots and model output are untrusted input. Never pass them to shell execution or privileged code.

## Named UI targets and scene planning

The perception layer can turn accessible controls into screenshot-scoped IDs such as
`paint.shape.ellipse` and `paint.color.red`. The local planner receives an `available_targets`
list with each target's bounds, centre, confidence and detection source. It can return
`click_target` with an exact ID; the runner detects the targets again from the fresh
pre-dispatch screenshot before clicking. Old target coordinates are never replayed blindly.

For visual-only palette controls, `ColorSwatchDetector` can locate a colour inside a
caller-supplied palette region. The region must be grounded in the current UI observation;
the detector intentionally does not scan the entire desktop for arbitrary matching pixels.

Artwork can be represented by `ScenePlan` objects using normalized canvas coordinates
(0 to 1), ordered layers, reusable styles, and ellipse/rectangle/polygon/path primitives.
`CanvasRegion` resolves those normalized objects to current screen pixels. Cubic Bezier and
ellipse helpers generate deterministic paths independently of the vision model.

## Scene planning and drawing execution

The scene planner and executor are separate from the one-step desktop task planner. The scene
planner creates normalized geometry; the executor grounds that geometry to the live canvas and
sends bounded strokes.

```python
from qwencoder_cua import Computer, DrawingExecutor, OllamaScenePlanner, TaskPolicy

scene = OllamaScenePlanner().plan(
    "Draw a simple sun above two rolling hills. Use outline shapes.",
    canvas_target_id="paint.canvas.canvas",
)

with Computer() as computer:
    executor = DrawingExecutor(computer, policy=TaskPolicy(max_steps=15))
    preview = executor.preview(scene)  # resolves geometry; does not draw
    result = executor.execute(scene)
    print(result.success, result.message)
```

The exact canvas target ID depends on what the current accessibility/visual detector exposes.
Inspect the target registry or inject a TargetDetector with a visual detector that emits the
desired `paint.canvas.*` ID. The executor re-detects the canvas before every stroke and resolves
normalized points against that fresh observation rather than replaying old screen coordinates.

The default executor supports outline-only, one-pixel black strokes and assumes the target
application's current tool is configured for freehand drawing. It does not select Paint tools,
change colours, change brush width, fill shapes, set opacity, create native vector objects or
manage layers. A caller may provide a `style_applier(DrawingStyle)` callback for application-
specific stroke colour/width setup; fills and opacity remain unsupported. Use a freehand/brush
tool, not a shape tool that interprets a path as a shape bounding-box drag.

Long paths are split into overlapping chunks within the configured 2–64 waypoint limit. Each
chunk is independently re-observed and screenshot-difference verified. Execution stops at the
first missing canvas, invalid geometry, failed verification, approval denial or policy limit.
Pass `approval_required=True` with an `approve(step, index)` callback to gate every stroke.
