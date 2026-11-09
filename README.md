# QWENCODER CUA Driver

**Version 0.3.0** — local-first Python desktop automation for Windows and Linux.
Hybrid strategy: accessibility semantics first, screenshot/coordinate interaction as fallback.

## v0.3 highlights

- Windows UI Automation through pywinauto and Linux AT-SPI accessibility trees.
- Semantic selectors to find controls again after a UI refresh.
- Ambiguous and empty selectors fail closed; no guessing between similarly named controls.
- `act_and_verify()` returns structured results separating input invocation from observed success.
- Postconditions for element presence/absence, values and active-window title.
- Wayland XDG portal readiness diagnostics via `qwencoder-cua portal-status`.

## Platform status

| Capability | Windows 10/11 | Rocky Linux X11 | Rocky Linux Wayland |
|---|---:|---:|---:|
| Screenshot and coordinate input | Yes | Yes | Not implemented |
| Accessibility tree | UIA | AT-SPI | AT-SPI may be available |
| Semantic actions | UIA | AT-SPI | Depends on app AT-SPI support |
| Re-identification and verification | Yes | Yes | If accessibility tree is available |
| Portal readiness probe | N/A | N/A | Yes |
| Portal screen capture/input stream | N/A | N/A | Not implemented in v0.3 |

Wayland diagnostics do not start a ScreenCast/RemoteDesktop session or bypass the consent dialog. Actual portal capture and PipeWire streaming remain future work. The Linux visual backend in this release targets X11 only.

## Requirements and installation

Python 3.11+ and a logged-in desktop session.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[windows,dev]"
python scripts/doctor.py
pytest -q
```

### Rocky Linux

```bash
sudo dnf install -y python3.11 python3.11-devel gcc libX11 libXtst at-spi2-core
# Install distribution-provided pyatspi bindings if available.
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[linux,dev]"
python scripts/doctor.py
pytest -q
```

AT-SPI Python bindings are commonly supplied by the Linux distribution rather than PyPI. Install the supported distro package and ensure at-spi2-core is running.

## Quick start

```python
from qwencoder_cua import Computer, ElementSelector

with Computer() as cua:
    observation = cua.observe()
    print(observation.platform, observation.active_window)
    print("accessible elements:", len(observation.elements))

    save = cua.find_element(ElementSelector(
        role="button", name="Save", automation_id="saveBtn"
    ))
    result = cua.act_and_verify(
        save.id,
        "click",
        {"element_present": {"role": "text", "name": "Saved"}},
        timeout=4.0,
    )
    print(result.success, result.verified, result.verification)
```

Re-identify a target after UI changes:

```python
fresh_save = cua.reidentify({
    "role": "button", "name": "Save", "automation_id": "saveBtn"
})
cua.click_element(fresh_save.id)
```

Supported expectation examples:

```python
{"element_absent": {"role": "dialog", "name": "Confirm"}}
{"element_present": {"role": "text", "name": "Saved"}}
{"element_value": {"selector": {"role": "edit", "automation_id": "filename"}, "equals": "scene.usd"}}
{"active_window_title_contains": "Houdini"}
```

`success` means the provider accepted the input action. `verified` means the postcondition was observed; callers should not treat an unverified action as complete.

## CLI

```bash
qwencoder-cua version
qwencoder-cua doctor
qwencoder-cua screenshot --output desktop.png
qwencoder-cua windows
qwencoder-cua inspect --max-depth 10
qwencoder-cua portal-status
```

## Safety

- Local process only; no network listener or cloud dependency.
- Element IDs expire and are invalidated on every observation.
- Ambiguous semantic selectors are rejected rather than guessed.
- OS permission prompts remain under user control.
- UI content is untrusted; never pass UI text directly to shell execution or privileged commands.
