# Architecture — v0.4

## Desktop driver selection

- Windows uses the Win32 visual/input backend and UI Automation provider.
- Linux X11 uses the Xlib/XTest backend and AT-SPI provider.
- Linux Wayland uses the portal backend. It never falls back to X11 global input.

## Wayland session lifecycle

1. Connect to the user's session D-Bus and introspect the XDG Desktop Portal.
2. Call RemoteDesktop.CreateSession, SelectDevices (keyboard + pointer), and ScreenCast.SelectSources (one monitor).
3. Call RemoteDesktop.Start. The desktop portal displays the consent UI; only user-approved device bits and streams are accepted.
4. Call ScreenCast.OpenPipeWireRemote for the restricted PipeWire FD associated with the RemoteDesktop session.
5. Use GStreamer's `pipewiresrc` with that FD and the selected stream target to capture a frame.
6. Send pointer/keyboard input using RemoteDesktop Notify methods only when those device classes were granted.
7. Close the portal Session and the PipeWire FD on disconnect.

The session is created through RemoteDesktop so ScreenCast shares the same session. The portal response may grant a subset of requested input devices. The driver exposes those actual capabilities and rejects denied operations. If screen sharing is approved without input, capture works but input remains unavailable.

## Task planning

`TaskPlanner.plan_next(goal, observation, history)` returns a `TaskDecision`: either a single `TaskStep` or a completed decision. `OllamaTaskPlanner` implements this contract through the local Ollama `/api/chat` endpoint. It supplies a compressed screenshot and a bounded accessibility summary when present.

The runner validates each step against a Pydantic schema, checks the action allow-list and policy limits, optionally requests user approval, dispatches exactly one action, then re-observes and verifies its postcondition. Only a verified step is followed by another planner call. Fixed plans can also be executed with `TaskRunner.execute()`.

## Verification

Semantic postconditions cover element presence/absence, accessible value and active-window title. The visual `screen_changed` condition compares downsampled before/after screenshots and checks the fraction of pixels that changed. This is a weak visual signal, not a semantic guarantee; use accessibility assertions where possible.

## Boundaries

The planner emits data, not executable code. Task actions are limited to click, text, key, scroll and semantic element operations. Shell execution, arbitrary Python, app launch, and unrestricted tools are intentionally excluded.

Wayland window enumeration/focus is not provided by the RemoteDesktop portal. Portal dialog interaction remains the user's responsibility.
