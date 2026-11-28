"""Local capability-token gate for the AI API (C2.1).

The token is a high-entropy bearer credential held only in process memory. It
is never written to logs, URLs, the database or Git. The desktop shell creates
it before importing the backend and hands it to the trusted WebView through a
pywebview bridge; a plain browser cannot obtain it safely, so browser AI
features stay disabled unless an operator explicitly provisions a token.
"""
from __future__ import annotations

import hmac
import os
import secrets
import threading

CAPABILITY_HEADER = "X-Hephaestus-Capability"
ENV_TOKEN = "HEPHAESTUS_AI_TOKEN"
_MIN_TOKEN_BYTES = 32

_lock = threading.Lock()
_token: str | None = None


def new_capability_token() -> str:
    """48 random bytes -> 64 URL-safe characters."""
    return secrets.token_urlsafe(48)


def configure_capability_token(token: str | None = None) -> str:
    """Set the process token once. An explicitly supplied token must be strong."""
    global _token
    value = (token or os.getenv(ENV_TOKEN) or "").strip()
    if value:
        if len(value) < _MIN_TOKEN_BYTES:
            raise RuntimeError("AI capability token is too short")
    else:
        value = new_capability_token()
    with _lock:
        _token = value
    return value


def ensure_capability_token() -> str:
    """Set a token only when the process has none; used at app startup."""
    if _token is not None:
        return _token
    return configure_capability_token()


def current_token() -> str:
    global _token
    if _token is None:
        return configure_capability_token()
    return _token


def verify_capability(value: str | None) -> bool:
    if not value:
        return False
    expected = current_token()
    try:
        return hmac.compare_digest(value, expected)
    except (TypeError, ValueError):
        return False


def reset_for_tests() -> None:
    global _token
    with _lock:
        _token = None