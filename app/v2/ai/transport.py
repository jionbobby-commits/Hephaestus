"""Small HTTP transport with proxy bypass, no redirects and a byte cap."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


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
    ) -> HttpResponse:
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[override]
        return None


class UrllibTransport:
    """Direct connection to the provider.

    Environment proxies are ignored on purpose: a local Ollama URL must never be
    sent to an HTTP proxy, and an API key must not be forwarded to one by accident.
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
    ) -> HttpResponse:
        data = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ResponseTooLarge(max_bytes)
                return HttpResponse(
                    status=int(response.status),
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(max_bytes + 1)
            finally:
                exc.close()
            if len(body) > max_bytes:
                raise ResponseTooLarge(max_bytes) from exc
            return HttpResponse(
                status=int(exc.code),
                headers={k.lower(): v for k, v in (exc.headers or {}).items()},
                body=body,
            )
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise TransportTimeout(str(reason)) from exc
            raise TransportConnectionError(str(reason)) from exc
        except TimeoutError as exc:
            raise TransportTimeout(str(exc)) from exc
        except OSError as exc:
            raise TransportConnectionError(str(exc)) from exc


def default_transport() -> HttpTransport:
    return UrllibTransport()
