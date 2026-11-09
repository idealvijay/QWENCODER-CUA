# Changelog

## 0.4.0
- Implement a consent-aware Wayland RemoteDesktop + ScreenCast session backend.
- Capture screenshots through the portal-restricted PipeWire remote FD and GStreamer PipeWire source.
- Send pointer/keyboard events through portal Notify methods only for user-granted device classes.
- Add closed-loop one-step-at-a-time TaskPlanner and TaskRunner APIs.
- Add local Ollama planner using structured JSON decisions, screenshots and accessibility context.
- Add allow-listed actions, step/runtime/text limits, required postconditions and approval gates.
- Add screenshot-difference verification for visual-only applications.
- Extend CLI with run-plan and run-goal commands.
