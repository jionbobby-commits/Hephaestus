"""URL/SSRF validation and redaction for the AI provider layer.

The checks below deliberately resolve names and reject metadata/link-local
addresses. They do not pin DNS: a determined attacker can still change DNS
between validation and request, so redirects are disabled and future releases
should reuse the resolved address. This is documented as a residual risk.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import uuid
from urllib.parse import urlsplit

from app.v2.ai.errors import AIError

OPENAI_COMPATIBLE_KINDS = {"openai", "deepseek", "qwen", "custom"}
SUPPORTED_KINDS = {"ollama"} | OPENAI_COMPATIBLE_KINDS

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;&]+"),
    re.compile(r"(?i)(sk-[a-z0-9_-]{8,})"),
)


def redact_secret(value: str, *, limit: int = 400) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "[REDACTED]") + "[REDACTED]", text)
    return text[:limit]


def safe_endpoint(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = None
    suffix = f":{port}" if port else ""
    return f"{parts.scheme}://{host}{suffix}{parts.path}"


def new_key_ref() -> str:
    return f"provider-{uuid.uuid4().hex}"


def _ip_allowed(ip: ipaddress._BaseAddress, *, allow_private: bool) -> bool:
    if ip.is_loopback:
        return True
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return False
    if ip.is_private:
        return allow_private
    return True


def _resolved_addresses(host: str, port: int) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AIError("invalid_base_url", "Base URL 无法解析，请检查域名或网络", status_code=422, details={"reason": type(exc).__name__}) from exc
    result: list[ipaddress._BaseAddress] = []
    for info in infos:
        address = info[4][0]
        try:
            result.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    if not result:
        raise AIError("invalid_base_url", "Base URL 无法解析出有效地址", status_code=422)
    return result


def validate_base_url(
    kind: str,
    value: str,
    *,
    platform: str = "web",
    resolve: bool = True,
    resolver=None,
) -> str:
    raw = (value or "").strip()
    if not raw or len(raw) > 2048:
        raise AIError("invalid_base_url", "Base URL 长度不合法", status_code=422)
    if any(ch.isspace() or ord(ch) < 32 for ch in raw):
        raise AIError("invalid_base_url", "Base URL 不能包含空白或控制字符", status_code=422)
    if "@" in raw:
        raise AIError("invalid_base_url", "Base URL 不能包含用户名或密码", status_code=422)
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise AIError("invalid_base_url", "Base URL 格式不合法", status_code=422) from exc
    if parts.scheme not in {"http", "https"}:
        raise AIError("invalid_base_url", "Base URL 只支持 http 或 https", status_code=422)
    host = (parts.hostname or "").strip()
    if not host:
        raise AIError("invalid_base_url", "Base URL 缺少主机名", status_code=422)
    if parts.query or parts.fragment:
        raise AIError("invalid_base_url", "Base URL 不能包含查询参数或片段", status_code=422)
    if port is not None and not (1 <= port <= 65535):
        raise AIError("invalid_base_url", "Base URL 端口不合法", status_code=422)
    if platform == "mobile" and kind == "ollama":
        raise AIError("mobile_ollama_forbidden", "移动端不支持 Ollama 本地运行，请使用在线 API", status_code=403)

    allow_private = kind == "ollama" or os.getenv("HEPHAESTUS_AI_ALLOW_PRIVATE_URLS", "").lower() in {"1", "true", "yes"}
    host_ip: ipaddress._BaseAddress | None = None
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None

    if host_ip is not None and not _ip_allowed(host_ip, allow_private=allow_private):
        raise AIError("invalid_base_url", "Base URL 指向不允许的内网或保留地址", status_code=422)
    if host_ip is None and resolve:
        addresses = resolver(host, port or (443 if parts.scheme == "https" else 80)) if resolver else _resolved_addresses(host, port or (443 if parts.scheme == "https" else 80))
        if not addresses:
            raise AIError("invalid_base_url", "Base URL 无法解析出有效地址", status_code=422)
        for address in addresses:
            if not _ip_allowed(address, allow_private=allow_private):
                raise AIError("invalid_base_url", "Base URL 解析到不允许的内网或保留地址", status_code=422)

    if kind != "ollama" and parts.scheme != "https" and not (host_ip and host_ip.is_loopback):
        if not (host_ip is None and host.lower() == "localhost"):
            raise AIError("invalid_base_url", "在线 API 必须使用 https；本机地址可用 http", status_code=422)

    path = parts.path.rstrip("/")
    netloc = parts.netloc
    if ":" in host and host_ip is not None and host_ip.version == 6:
        netloc = f"[{host}]" + (f":{port}" if port else "")
    normalized = f"{parts.scheme}://{netloc}{path}"
    return normalized


def provider_label(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AIError("invalid_request", "配置名称不能为空", status_code=422)
    return text


def provider_model(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AIError("invalid_request", "模型名称不能为空", status_code=422)
    if len(text) > 200 or any(ord(ch) < 32 for ch in text):
        raise AIError("invalid_request", "模型名称不合法", status_code=422)
    return text
