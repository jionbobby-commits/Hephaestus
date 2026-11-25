"""Unified, redacted errors for AI provider operations."""
from __future__ import annotations

from typing import Any

from app.v2.contracts import AIErrorInfo, AIErrorResponse


class AIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        provider_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.provider_id = provider_id
        self.retryable = retryable
        self.details = details or {}

    def to_response(self) -> AIErrorResponse:
        return AIErrorResponse(
            error=AIErrorInfo(
                code=self.code,
                message=self.message,
                provider_id=self.provider_id,
                retryable=self.retryable,
                details=self.details,
            )
        )
