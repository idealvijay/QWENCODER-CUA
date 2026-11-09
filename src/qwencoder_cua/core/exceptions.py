class CUAError(RuntimeError):
    """Base exception for driver errors."""


class DriverUnavailableError(CUAError):
    pass


class UnsupportedOperationError(CUAError):
    pass


class PermissionDeniedError(CUAError):
    pass


class StaleTargetError(CUAError):
    pass
