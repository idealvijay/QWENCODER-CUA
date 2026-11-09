# Security model — v0.4

- Local-first execution; Ollama defaults to loopback at `127.0.0.1:11434`.
- Planner responses are untrusted structured data and are validated with strict Pydantic models.
- Only an explicit action allow-list is executable. There are no shell, Python, app-launch or arbitrary tool-call plan actions.
- Task execution is bounded by maximum steps, runtime, text length and per-step verification timeout.
- Every step must declare a postcondition. A failed or unverified step stops the default run.
- Consequential steps may set `approval_required`; CLI approval defaults to no.
- Wayland capture and input use the portal-authorized session and PipeWire remote FD. No portal consent flow is bypassed.
- The user can grant screen sharing separately from keyboard/pointer input; denied device methods raise errors.
- Screenshot files are temporary during planning and verification and are removed after each step.
- Screenshots, accessible values, window titles, task goals and model output may contain sensitive data.
- Never forward untrusted UI content to shell execution, eval, privileged code, or external services without explicit configuration.
