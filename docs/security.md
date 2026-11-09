# Security model

- Local process only; no network listener or cloud dependency.
- No privilege escalation or OS security-boundary bypass.
- Element tokens are random, short-lived and invalidated on every observation.
- Providers reject disabled controls and unsupported actions.
- UIA/AT-SPI object wrappers are process-local and must be refreshed after UI changes.
- Treat screenshots, labels, values and window titles as potentially sensitive.
- Do not feed untrusted UI text to shell execution or privileged commands.
- For high-impact actions, require an application-level confirmation step in the agent.
