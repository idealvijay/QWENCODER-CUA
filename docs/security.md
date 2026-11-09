# Security model — v0.3

- Local process only; no network listener or cloud execution.
- No privilege escalation or OS security-boundary bypass.
- Desktop portal consent remains controlled by the user and desktop environment.
- Element tokens are random, short-lived and invalidated on every observation.
- Ambiguous selectors fail closed.
- Verification reports observed UI state separately from input invocation success.
- Screenshots, labels, window titles and accessible values may contain sensitive data.
- Never pass untrusted UI text directly to shell execution, eval, or privileged commands.
