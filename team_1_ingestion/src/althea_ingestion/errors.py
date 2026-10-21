class StorageError(RuntimeError):
    """Base class for storage layer errors.

    Attributes:
        code (str): Machine‑readable error code.
        retryable (bool): Whether the operation may succeed if retried.
        stage (str): Logical stage where the error occurred (e.g. "storage").
        message (str): Safe human‑readable description (no secrets).
    """

    def __init__(self, code: str, retryable: bool, stage: str, message: str):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.stage = stage
        self.message = message

# Specific error codes used by the storage layer.
BUDGET_LIMIT = "BUDGET_LIMIT"
NOT_FOUND = "NOT_FOUND"
STORAGE_ERROR = "STORAGE_ERROR"
CONTRACT_INVALID = "CONTRACT_INVALID"
