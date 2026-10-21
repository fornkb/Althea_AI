class AppError(RuntimeError):
    def __init__(self, code, message, *, stage='integration', retryable=False):
        super().__init__(message)
        self.code, self.stage, self.retryable = code, stage, retryable


def require(condition, message, code='CONTRACT_INVALID'):
    if not condition:
        raise AppError(code, message)


def issue(code, message, *, stage='integration', related_ids=None, retryable=False):
    return dict(stage=stage,code=code,message=message,retryable=retryable,related_ids=related_ids or [])
