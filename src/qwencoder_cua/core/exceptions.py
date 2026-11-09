class CUAError(RuntimeError):
    pass


class DriverUnavailableError(CUAError):
    pass


class UnsupportedOperationError(CUAError):
    pass


class StaleElementError(CUAError):
    pass


class AmbiguousElementError(CUAError):
    pass


class VerificationError(CUAError):
    pass
