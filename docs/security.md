# Security

- Operate only on a desktop session the user owns or is authorized to control.
- Do not run as a privileged service or Linux root user.
- Keep input restricted to the current interactive user session.
- No arbitrary shell command API is exposed.
- Clipboard read is intentionally not implemented by default.
- Wayland global capture/input is not bypassed; use user-authorized portals.
- Never log typed text, passwords, clipboard contents or screenshot pixels by default.
- Add explicit confirmation gates before destructive file, account or system actions.
