"""Pinned HTTP transport with proxy bypass, no redirects and a byte cap.

The AI URL validator resolves a hostname once and returns the addresses. This
transport connects to one of those addresses directly, so a DNS answer cannot
change between validation and the request (DNS rebinding). HTTPS still uses the
original hostname for SNI and certificate verification.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from urllib.parse import urlsplit


class TransportTimeout(Exception):
    pass


class TransportConnectionError(Exception):
    pass


class ResponseTooLarge(Exception):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: float,
        max_bytes: int,
        resolved_ips: Sequence[str] | None = None,
    ) -> HttpResponse:
        ...


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, connect_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._connect_ip = connect_ip

    def connect(self) -> None:  # type: ignore[override]
        self.sock = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_ip: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._connect_ip = connect_ip

    def connect(self) -> None:  # type: ignore[override]
        sock = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address
        )
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _resolve_host(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise TransportConnectionError(f"DNS resolution failed: {type(exc).__name__}") from exc
    result: list[str] = []
    seen: set[str] = set()
    for info in infos:
        value = info[4][0]
        try:
            parsed = str(ipaddress.ip_address(value))
        except ValueError:
            continue
        if parsed not in seen:
            seen.add(parsed)
            result.append(parsed)
    if not result:
        raise TransportConnectionError("no usable address")
    return result


def _normalize_ips(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            parsed = str(ipaddress.ip_address(str(value)))
        except ValueError:
            continue
        if parsed not in seen:
            seen.add(parsed)
            result.append(parsed)
    return result


class PinnedHttpTransport:
    """Direct HTTP(S) connection to an already validated IP address.

    Environment proxies are ignored on purpose: a local Ollama URL must never be
    sent to an HTTP proxy, and an API key must not be forwarded to one by
    accident. No redirect is followed.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        timeout: float,
        max_bytes: int,
        resolved_ips: Sequence[str] | None = None,
    ) -> HttpResponse:
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as exc:
            raise TransportConnectionError("invalid URL") from exc
        if parts.scheme not in {"http", "https"} or not host:
            raise TransportConnectionError("invalid URL")

        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"

        data = None
        request_headers = {
            key: value for key, value in headers.items() if key.lower() != "host"
        }
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        addresses = (
            _resolve_host(host, port)
            if resolved_ips is None
            else _normalize_ips(resolved_ips)
        )
        if not addresses:
            raise TransportConnectionError("no validated address")

        context = ssl.create_default_context() if parts.scheme == "https" else None
        last_error: Exception | None = None
        for address in addresses:
            connection: http.client.HTTPConnection | None = None
            sent = False
            try:
                if parts.scheme == "https":
                    connection = _PinnedHTTPSConnection(
                        host, port, connect_ip=address, timeout=timeout, context=context  # type: ignore[arg-type]
                    )
                else:
                    connection = _PinnedHTTPConnection(
                        host, port, connect_ip=address, timeout=timeout
                    )
                # Connect before sending so a failed address can be retried
                # without risking a duplicate POST.
                connection.connect()
                sent = True
                connection.request(method, path, body=data, headers=request_headers)
                response = connection.getresponse()
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ResponseTooLarge(max_bytes)
                return HttpResponse(
                    status=int(response.status),
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=body,
                )
            except ResponseTooLarge:
                raise
            except (TransportTimeout, TransportConnectionError):
                raise
            except ssl.SSLCertVerificationError as exc:
                last_error = exc
                if sent:
                    raise TransportConnectionError("TLS certificate verification failed") from exc
            except (TimeoutError, socket.timeout) as exc:
                if sent:
                    raise TransportTimeout(str(exc)) from exc
                last_error = exc
            except (OSError, http.client.HTTPException) as exc:
                if sent:
                    raise TransportConnectionError(f"connection failed: {type(exc).__name__}") from exc
                last_error = exc
            finally:
                if connection is not None:
                    connection.close()

        raise TransportConnectionError(
            f"connection failed: {type(last_error).__name__ if last_error else 'unknown'}"
        )


# Backwards-compatible name used by early C1 docs/callers.
UrllibTransport = PinnedHttpTransport


def default_transport() -> HttpTransport:
    return PinnedHttpTransport()
