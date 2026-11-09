# Changelog

## 0.5.1
- Treat user-provided blank-canvas state as authoritative unless visible marks clearly contradict it.
- Prefer Paint's ellipse shape with no fill and red outline for circle requests when controls are visible.
- Align vision-model pointer coordinates with the resized screenshot and map them to desktop pixels.
- Apply bounds validation and coordinate mapping to click, move, drag and draw-path actions.


## 0.5.0
- Add held-button mouse input and atomic straight-line drag / multi-waypoint drawing paths.
- Implement Windows, Linux X11 and consent-gated Wayland pointer press/release adapters.
- Guarantee best-effort pointer release after drawing-path failures.
- Add bounded planner actions for pointer movement, drag and draw path.
- Validate drawing waypoint count, duration and coordinates against captured desktop dimensions.
- Add circle and rectangle polyline helpers for application-independent drawing.

## 0.4.0
- Implement a consent-aware Wayland RemoteDesktop + ScreenCast session backend.
- Capture screenshots through the portal-restricted PipeWire remote FD and GStreamer PipeWire source.
- Send pointer/keyboard events through portal Notify methods only for user-granted device classes.
- Add closed-loop one-step-at-a-time TaskPlanner and TaskRunner APIs.
- Add local Ollama planner using structured JSON decisions, screenshots and accessibility context.
- Add allow-listed actions, step/runtime/text limits, required postconditions and approval gates.
- Add screenshot-difference verification for visual-only applications.
- Extend CLI with run-plan and run-goal commands.
