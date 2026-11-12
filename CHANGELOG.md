# Changelog

## 0.5.4
- Detect terminal vision-model responses that incorrectly ask the user to perform normal Paint drawing setup while Paint is already active.
- Re-prompt the model once to produce a concrete allowed UI action; preserve manual foreground-window hand-offs and stop safely if the model repeats the hand-off.
- Strengthen planner guidance that colour/tool/shape selection is part of the agent's work.

## 0.5.3
- Validate model-generated click, move, drag and draw-path coordinates against the resized vision image before accepting a planner decision.
- When coordinates are outside image bounds, return dimensions and offending points to the model for one bounded replan.
- Refuse a second invalid coordinate response without dispatching it.
- Clarify that the planner must use screen_size (resized image) coordinates, never desktop_size coordinates.

# Changelog

## 0.5.2
- Prefer screen-change verification for coordinate-driven Paint/Photoshop interactions.
- Ignore unsupported model-generated extra postcondition keys only when a supported screen-change check is also present.
- Preserve all supported semantic/window assertions and continue rejecting unknown-only expectations.
- Clarify that desktop-resolution resizing is mapped using each fresh observation's current screenshot dimensions.

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
