from dataclasses import dataclass, field


@dataclass
class PermissionPolicy:
    """Conservative local permission policy. No arbitrary shell execution is exposed."""
    allow_input: bool = True
    allow_clipboard_read: bool = False
    allowed_application_commands: set[str] = field(default_factory=set)

    def require_input(self):
        if not self.allow_input:
            from qwencoder_cua.core.exceptions import PermissionDeniedError
            raise PermissionDeniedError("Input actions are disabled by policy.")
