class ComponentError(RuntimeError):
    def __init__(self, code, message, *, stage='input', retryable=False):
        super().__init__(message)
        self.code, self.stage, self.retryable = code, stage, retryable


IngestionError = ComponentError


def require(condition, message, code='CONTRACT_INVALID'):
    if not condition:
        raise ComponentError(code, message)
