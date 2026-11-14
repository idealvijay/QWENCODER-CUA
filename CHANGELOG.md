# Changelog

## 0.6.0
- Add screenshot-scoped named UI targets with accessibility classification, confidence and bounds.
- Add target registry freshness checks and named `click_target` planning/execution with pre-dispatch re-detection.
- Add explicit-region colour swatch detection for palette grounding.
- Add normalized canvas-relative scene models, ordered drawing objects and style metadata.
- Add deterministic ellipse, cubic Bezier and polygon geometry helpers plus desktop-coordinate scene resolution.

## 0.5.8
- Normalize flattened numeric coordinate pairs and two-item coordinate arrays into draw-path point objects.
- Preserve the 2-64 waypoint validation limit; never truncate oversized paths.
- Strengthen vision-planner guidance for smooth circles, preferring Paint's native ellipse tool and limiting freehand circles to 12-24 evenly spaced waypoints.

## 0.5.7
- Permit one fresh observe/replan cycle after a Paint drawing setup click is dispatched but produces no detected screen change.
- Include the failed click point in planner history and instruct the model not to repeat it.
- Keep the recovery bounded to one retry and only for Paint drawing goals; other failed actions retain fail-fast behavior.

## 0.5.6
- For coordinate-driven pointer actions, use the screenshot-difference postcondition as the sole visual verification oracle when present.
- Drop model-invented semantic element checks that can fail despite a verified visible screen change.
- Preserve combined semantic and visual checks for accessibility-driven semantic actions.

## 0.5.5
- Detect planner hand-offs that claim another app is visible while OS metadata reports the requested Paint/Photoshop app as foreground.
- Re-prompt once with the foreground title/process metadata and explicit screenshot reconciliation guidance.
- If the screenshot/window conflict remains unresolved, fail safely without dispatching an input action.
- Preserve legitimate app-switch hand-offs when another application is actually foreground.

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
