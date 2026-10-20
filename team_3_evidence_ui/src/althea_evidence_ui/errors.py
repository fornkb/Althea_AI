"""Error definitions for althea_evidence_ui."""
from __future__ import annotations
from typing import Literal

SafeStage = Literal["input", "transcription", "analysis", "verification", "storage", "integration"]

SAFE_CODES = {
    "INVALID_INPUT",
    "AUDIO_TOO_LONG",
    "AUDIO_TOO_LARGE",
    "FFMPEG_MISSING",
    "PROVIDER_AUTH",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMIT",
    "PROVIDER_RESPONSE_INVALID",
    "BUDGET_LIMIT",
    "CONTRACT_INVALID",
    "NOT_FOUND",
    "STORAGE_ERROR",
}


class AltheaError(RuntimeError):
    """Base error for all Althea runtime and contract failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: SafeStage = "verification",
        retryable: bool = False,
        related_ids: list[str] | None = None,
    ):
        super().__init__(message)
        if code not in SAFE_CODES:
            # Fall back to CONTRACT_INVALID or INVALID_INPUT if code not strictly in set
            code = "CONTRACT_INVALID"
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.message = message
        self.related_ids = related_ids or []

    def to_issue(self) -> dict:
        return {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "related_ids": self.related_ids,
        }


class ContractError(AltheaError):
    def __init__(self, message: str, *, related_ids: list[str] | None = None):
        super().__init__(
            message,
            code="CONTRACT_INVALID",
            stage="verification",
            retryable=False,
            related_ids=related_ids,
        )


class BudgetLimitError(AltheaError):
    def __init__(self, message: str = "Provider attempt budget exceeded", *, related_ids: list[str] | None = None):
        super().__init__(
            message,
            code="BUDGET_LIMIT",
            stage="verification",
            retryable=False,
            related_ids=related_ids,
        )


class ProviderError(AltheaError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "PROVIDER_UNAVAILABLE",
        stage: SafeStage = "verification",
        retryable: bool = True,
        related_ids: list[str] | None = None,
    ):
        super().__init__(
            message,
            code=code,
            stage=stage,
            retryable=retryable,
            related_ids=related_ids,
        )


class NotFoundError(AltheaError):
    def __init__(self, message: str, *, related_ids: list[str] | None = None):
        super().__init__(
            message,
            code="NOT_FOUND",
            stage="verification",
            retryable=False,
            related_ids=related_ids,
        )


class InvalidInputError(AltheaError):
    def __init__(self, message: str, *, related_ids: list[str] | None = None):
        super().__init__(
            message,
            code="INVALID_INPUT",
            stage="verification",
            retryable=False,
            related_ids=related_ids,
        )
