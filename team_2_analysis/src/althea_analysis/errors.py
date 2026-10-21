"""Safe errors shared through attributes, without coupling integrations to classes."""


class AnalysisError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable=False, stage="analysis"):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.stage = stage


def invalid(message="The provider response could not be validated."):
    return AnalysisError("PROVIDER_RESPONSE_INVALID", message)
