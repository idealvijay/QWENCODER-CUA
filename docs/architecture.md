# Architecture — v0.2

## Hybrid perception

1. `Computer.observe()` captures a screenshot and window metadata.
2. The platform accessibility provider enumerates semantic elements when available.
3. The facade assigns random observation-scoped tokens with a short TTL.
4. The agent chooses semantic actions when possible; otherwise it can use coordinates.
5. A new observation invalidates all prior tokens.

## Provider boundaries

`AccessibilityProvider` is independent of visual drivers. Windows uses UI Automation through pywinauto. Linux uses AT-SPI through pyatspi. Both normalize into `UIElement`. This avoids pretending that Windows UIA and Linux AT-SPI expose identical metadata.

## Linux session strategy

- X11: existing Xlib/XTest backend handles capture and global input.
- Wayland: no global input/capture adapter in this release. AT-SPI may still expose application semantics, but semantic action availability varies. Portal capture and remote-desktop input need a dedicated consent-aware implementation.
