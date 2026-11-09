# Architecture

The runtime is split into platform adapters, typed models, a synchronous public facade,
and optional transports. AI planning is deliberately outside this repository's core.

## Backend selection

- Windows: Win32 window APIs, MSS capture and PyAutoGUI input.
- Linux X11: python-xlib/XTest and MSS.
- Linux Wayland: detected explicitly; portal adapter is a future implementation.
- Unknown/headless sessions: fail with a diagnostic rather than guessing.

## Coordinate contract

The initial public API accepts physical desktop pixel coordinates in the coordinate
space returned by screenshot capture. Multi-monitor negative origins and per-monitor
DPI scaling need dedicated tests before being considered production-ready.

## Observation identity

Observation IDs are generated for each capture. Future element handles must include
the observation ID and become invalid after a new observation.

## Verification

The initial scaffold reports raw driver execution. It does not yet claim that an action
achieved the intended UI effect. A verifier is a required next milestone.
