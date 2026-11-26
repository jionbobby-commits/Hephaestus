"""Sanitise request-validation errors before they leave the API.

FastAPI/Pydantic include the offending input value in 422 responses. For a
model-level validator that input can be the whole request body, including an
API key. The AI config endpoints therefore install this handler and replace
known secret fields with a marker; locations and messages are preserved so
normal validation diagnostics still work.
"""
from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_SECRET_FIELDS = {
    "api_key",
    "apikey",
    "api_secret",
    "client_secret",
    "secret",
    "secret_key",
    "private_key",
    "key_ref",
    "password",
    "authorization",
    "access_token",
    "refresh_token",
    "token",
}
_REDACTED = "[REDACTED]"


def _field_name(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _is_secret_field(value: Any) -> bool:
    return _field_name(value) in _SECRET_FIELDS


def _sanitize(value: Any, field: Any = None) -> Any:
    if field is not None and _is_secret_field(field):
        return _REDACTED
    if isinstance(value, dict):
        return {key: _sanitize(item, key) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        item = dict(error)
        location = item.get("loc") or ()
        if any(_is_secret_field(part) for part in location):
            if "input" in item:
                item["input"] = _REDACTED
        elif "input" in item:
            item["input"] = _sanitize(item["input"])
        if "ctx" in item:
            item["ctx"] = _sanitize(item["ctx"])
        sanitized.append(item)
    return sanitized


async def validation_exception_handler(_request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(sanitize_validation_errors(exc.errors()))},
    )
