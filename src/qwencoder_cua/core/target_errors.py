from qwencoder_cua.core.exceptions import CUAError


class StaleTargetError(CUAError):
    """Raised when a target belongs to a previous screenshot observation."""


class TargetNotFoundError(CUAError):
    """Raised when a named target is not present in the current registry."""


class AmbiguousTargetError(CUAError):
    """Raised when more than one target matches a requested label or kind."""
