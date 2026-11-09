# Architecture — v0.3

## Hybrid perception and targeting

1. `Computer.observe()` captures a screenshot and window metadata.
2. The platform provider enumerates accessibility elements when available.
3. ElementTokenStore assigns random observation-scoped IDs and retains provider-local IDs separately.
4. Actions resolve the short-lived ID and restore the provider-local ID before dispatch.
5. Every new observation invalidates previous IDs, including when accessibility enumeration fails.
6. For changed UIs, `reidentify()` observes again and resolves a semantic ElementSelector. Zero or multiple matches stop the operation.

## Action verification

`act_and_verify()` invokes the provider action and polls fresh observations for a declarative postcondition. `success` means the provider accepted the input; `verified` means the requested resulting UI state was observed. These are intentionally separate.

Supported postconditions: `element_absent`, `element_present`, `element_value`, and `active_window_title_contains`. Semantic postconditions fail closed when accessibility data is unavailable.

## Provider boundaries

Windows uses UI Automation via pywinauto. Linux uses AT-SPI via distro-provided pyatspi bindings. Both normalize into UIElement. Platform-specific metadata remains optional.

## Wayland

`portal-status` checks for XDG Desktop Portal ScreenCast/RemoteDesktop interfaces and PipeWire tooling. It is diagnostic only. A real Wayland backend must request a user-consented portal session, negotiate PipeWire streams, decode frames and manage RemoteDesktop input. v0.3 does not pretend that readiness probing is functional capture/input.
