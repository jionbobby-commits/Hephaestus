"""HTTP boundary checks for the local AI API.

The API has no user authentication: its trust boundary is the local machine.
Validating only the socket peer is not enough, because a browser can be tricked
into sending a request to 127.0.0.1 with an attacker-controlled Host header
(DNS rebinding). This middleware checks Host and, when present, Origin/Referer
before any AI route runs. It also caps the request body.
"""
from __future__ import annotations

import json
import os
from typing import Awaitable, Callable

from app.v2.ai.capability import CAPABILITY_HEADER, verify_capability

MAX_AI_BODY_BYTES = 2_000_000
_AI_PREFIX = "/api/v2/ai"
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_host(value: str) -> tuple[str, int | None]:
    """Parse a Host/authority value without accepting userinfo or ambiguity."""
    raw = (value or "").strip()
    if not raw or len(raw) > 255:
        raise ValueError("empty or too long host")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in raw):
        raise ValueError("non-ASCII or control character")
    if any(ch in raw for ch in "/\\@,;?#"):
        raise ValueError("illegal host character")

    port: int | None = None
    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            raise ValueError("unterminated IPv6 host")
        host = raw[1:end]
        rest = raw[end + 1 :]
        if rest:
            if not rest.startswith(":"):
                raise ValueError("bad IPv6 authority")
            port = _parse_port(rest[1:])
        if ":" not in host:
            raise ValueError("bracketed host is not IPv6")
    else:
        if raw.count(":") > 1:
            raise ValueError("IPv6 host must be bracketed")
        if ":" in raw:
            host, port_text = raw.rsplit(":", 1)
            port = _parse_port(port_text)
        else:
            host = raw
    host = host.strip().lower().rstrip(".")
    if not host:
        raise ValueError("empty host")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789.-_:")
    if any(ch not in allowed for ch in host):
        raise ValueError("illegal host character")
    return host, port


def _parse_port(value: str) -> int:
    if not value or not value.isdigit():
        raise ValueError("bad port")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("bad port")
    return port


def _host_values(scope) -> list[str]:
    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == b"host"
    ]


def _header_values(scope, name: str) -> list[str]:
    raw = name.encode("latin-1")
    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == raw
    ]


def _allowed_hosts() -> list[tuple[str, int | None]]:
    result: list[tuple[str, int | None]] = [(host, None) for host in _LOCAL_HOSTS]
    for item in os.getenv("HEPHAESTUS_AI_ALLOWED_HOSTS", "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(_parse_host(item))
        except ValueError:
            continue
    return result


def _host_allowed(host: str, port: int | None, scope) -> bool:
    client = scope.get("client") or ()
    client_host = str(client[0]) if client else ""
    if host == "testserver" and client_host == "testclient":
        return True
    for allowed_host, allowed_port in _allowed_hosts():
        if host != allowed_host:
            continue
        if allowed_port is None or port == allowed_port:
            return True
    return False


def _origin_parts(value: str, *, allow_path: bool = False) -> tuple[str, int]:
    if value.strip().lower() == "null":
        raise ValueError("null origin")
    from urllib.parse import urlsplit

    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("bad origin")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("bad origin")
    if not allow_path and parts.path not in {"", "/"}:
        raise ValueError("bad origin path")
    host = parts.hostname.strip().lower().rstrip(".")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in host):
        raise ValueError("bad origin host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return host, port


def _same_origin(
    value: str,
    request_host: str,
    request_port: int | None,
    scheme: str,
    *,
    allow_path: bool = False,
) -> bool:
    host, port = _origin_parts(value, allow_path=allow_path)
    expected_port = request_port or (443 if scheme == "https" else 80)
    return host == request_host and port == expected_port


def _json_error(status: int, code: str, message: str) -> tuple[int, bytes]:
    body = json.dumps(
        {
            "error": {
                "code": code,
                "message": message,
                "provider_id": None,
                "retryable": False,
                "details": {},
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return status, body


async def _send_json(
    send: Callable[[dict], Awaitable[None]], status: int, code: str, message: str
) -> None:
    status, body = _json_error(status, code, message)
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive, limit: int) -> tuple[bytes | None, str | None]:
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None, "客户端已断开"
        if message["type"] != "http.request":
            continue
        body = message.get("body", b"")
        if not isinstance(body, (bytes, bytearray)):
            return None, "请求体格式不合法"
        total += len(body)
        if total > limit:
            return None, "请求体过大"
        chunks.append(bytes(body))
        if not message.get("more_body", False):
            return b"".join(chunks), None


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
    for index, (key, _) in enumerate(headers):
        if key.lower() == name:
            headers[index] = (key, value)
            return
    headers.append((name, value))


class AISecurityMiddleware:
    def __init__(self, app, *, max_body_bytes: int = MAX_AI_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = int(max_body_bytes)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if path != _AI_PREFIX and not path.startswith(_AI_PREFIX + "/"):
            await self.app(scope, receive, send)
            return

        allow_remote = _truthy("HEPHAESTUS_AI_ALLOW_REMOTE")
        request_host: str | None = None
        request_port: int | None = None
        host_values = _host_values(scope)
        if not allow_remote:
            if len(host_values) != 1:
                await _send_json(send, 403, "invalid_host", "Host 请求头不合法")
                return
            try:
                request_host, request_port = _parse_host(host_values[0])
            except ValueError:
                await _send_json(send, 403, "invalid_host", "Host 请求头不合法")
                return
            if not _host_allowed(request_host, request_port, scope):
                await _send_json(send, 403, "invalid_host", "AI 配置接口仅允许本机访问")
                return

            origins = _header_values(scope, "origin")
            referers = _header_values(scope, "referer")
            if len(origins) > 1 or len(referers) > 1:
                await _send_json(send, 403, "invalid_origin", "Origin 请求头不合法")
                return
            if origins:
                try:
                    same = _same_origin(
                        origins[0], request_host, request_port, str(scope.get("scheme") or "http")
                    )
                except ValueError:
                    same = False
                if not same:
                    await _send_json(send, 403, "invalid_origin", "跨站请求已被拒绝")
                    return
            elif referers:
                try:
                    same = _same_origin(
                        referers[0], request_host, request_port, str(scope.get("scheme") or "http"), allow_path=True
                    )
                except ValueError:
                    same = False
                if not same:
                    await _send_json(send, 403, "invalid_origin", "跨站请求已被拒绝")
                    return

        # C2.1: a local socket is not an identity. Every AI route requires the
        # per-process capability token, delivered out-of-band by the desktop
        # shell. The platform header is a UI hint, never an authorization claim.
        capabilities = _header_values(scope, CAPABILITY_HEADER.lower())
        if len(capabilities) != 1 or not verify_capability(capabilities[0].strip()):
            if not capabilities:
                await _send_json(send, 401, "missing_capability", "缺少本机 AI 访问令牌")
            else:
                await _send_json(send, 401, "invalid_capability", "本机 AI 访问令牌无效")
            return

        encodings = _header_values(scope, "content-encoding")
        if any(value.strip().lower() not in {"", "identity"} for value in encodings):
            await _send_json(send, 415, "unsupported_encoding", "不支持压缩的请求体")
            return

        lengths = _header_values(scope, "content-length")
        if len(lengths) > 1:
            await _send_json(send, 400, "invalid_content_length", "Content-Length 不合法")
            return
        if lengths:
            text = lengths[0].strip()
            if not text.isdigit():
                await _send_json(send, 400, "invalid_content_length", "Content-Length 不合法")
                return
            if int(text) > self.max_body_bytes:
                await _send_json(send, 413, "body_too_large", "请求体过大")
                return

        body, error = await _read_body(receive, self.max_body_bytes)
        if error is not None:
            status = 413 if error == "请求体过大" else 400
            code = "body_too_large" if status == 413 else "invalid_body"
            await _send_json(send, status, code, error)
            return

        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body or b"", "more_body": False}
            # Do not fake an immediate disconnect: StreamingResponse listens on
            # receive() and would cancel the stream before the first chunk.
            return await receive()

        async def send_security_headers(message):
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                _set_header(response_headers, b"cache-control", b"no-store")
                _set_header(response_headers, b"x-content-type-options", b"nosniff")
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, replay, send_security_headers)