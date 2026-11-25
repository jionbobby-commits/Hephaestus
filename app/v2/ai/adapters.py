"""Provider adapters.

Only this module knows provider URLs/payload shapes. The service layer passes a
ResolvedProvider and a transport; adapters never read the database or secret
store, and they never include request headers in errors.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.v2.ai.errors import AIError
from app.v2.ai.security import OPENAI_COMPATIBLE_KINDS, redact_secret, safe_endpoint
from app.v2.ai.transport import (
    HttpResponse,
    HttpTransport,
    ResponseTooLarge,
    TransportConnectionError,
    TransportTimeout,
)
from app.v2.contracts import AIChatMessage, AIChatUsage, AIModelInfo, AIProviderParams

DEFAULT_MAX_BYTES = 2_000_000


@dataclass
class ResolvedProvider:
    id: str
    kind: str
    label: str
    base_url: str
    model: str
    params: AIProviderParams
    api_key: str | None = field(default=None, repr=False)
    # Exact addresses resolved during validation; the transport pins to these.
    resolved_ips: tuple[str, ...] = ()


@dataclass
class ChatOutcome:
    content: str
    finish_reason: str | None = None
    usage: AIChatUsage | None = None


class _AdapterBase:
    def __init__(self, transport: HttpTransport, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.transport = transport
        self.max_bytes = max_bytes

    def _request_json(
        self,
        provider: ResolvedProvider,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.transport.request(
                method,
                url,
                headers=headers,
                json_body=payload,
                timeout=float(provider.params.timeout_seconds),
                max_bytes=self.max_bytes,
                resolved_ips=provider.resolved_ips or None,
            )
        except TransportTimeout as exc:
            raise AIError(
                "timeout",
                f"{provider.label} 请求超时（{provider.params.timeout_seconds:g} 秒）",
                status_code=504,
                provider_id=provider.id,
                retryable=True,
                details={"reason": type(exc).__name__},
            ) from exc
        except ResponseTooLarge as exc:
            raise AIError(
                "response_too_large",
                "模型服务返回内容过大，已中止",
                status_code=502,
                provider_id=provider.id,
                details={"limit_bytes": self.max_bytes},
            ) from exc
        except TransportConnectionError as exc:
            hint = "请确认 Ollama 已启动" if provider.kind == "ollama" else "请检查网络和 Base URL"
            raise AIError(
                "provider_unavailable",
                f"无法连接 {provider.label}：{hint}",
                status_code=503,
                provider_id=provider.id,
                retryable=True,
                details={"reason": type(exc).__name__},
            ) from exc
        except OSError as exc:
            raise AIError(
                "provider_unavailable",
                f"无法连接 {provider.label}",
                status_code=503,
                provider_id=provider.id,
                retryable=True,
                details={"reason": type(exc).__name__},
            ) from exc
        if not 200 <= response.status < 300:
            raise self._http_error(provider, response, url)
        return self._decode(provider, response)

    def _decode(self, provider: ResolvedProvider, response: HttpResponse) -> dict[str, Any]:
        raw = response.body.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            raise AIError(
                "invalid_provider_response",
                f"{provider.label} 返回了无法解析的响应",
                status_code=502,
                provider_id=provider.id,
                details={"status": response.status, "response": redact_secret(raw)},
            ) from exc
        if not isinstance(data, dict):
            raise AIError(
                "invalid_provider_response",
                f"{provider.label} 返回结构不符合预期",
                status_code=502,
                provider_id=provider.id,
                details={"status": response.status},
            )
        return data

    def _http_error(self, provider: ResolvedProvider, response: HttpResponse, url: str) -> AIError:
        body = response.body.decode("utf-8", errors="replace")
        excerpt = redact_secret(body)
        lowered = body.lower()
        details = {"status": response.status, "endpoint": safe_endpoint(url), "response": excerpt}
        if response.status in (401, 403):
            return AIError("auth_failed", f"{provider.label} 鉴权失败，请检查 API Key", status_code=401, provider_id=provider.id, details=details)
        if response.status == 404 and "model" in lowered and ("not found" in lowered or "does not exist" in lowered or "unknown" in lowered):
            return AIError("model_not_found", f"模型 {provider.model} 不存在或未安装", status_code=404, provider_id=provider.id, details=details)
        if response.status == 404:
            return AIError("invalid_base_url", f"{provider.label} 的接口地址不正确", status_code=404, provider_id=provider.id, details=details)
        if response.status == 429:
            return AIError("rate_limited", f"{provider.label} 请求过于频繁，请稍后再试", status_code=429, provider_id=provider.id, retryable=True, details=details)
        if response.status in (400, 422):
            return AIError("invalid_request", f"{provider.label} 拒绝了请求参数", status_code=422, provider_id=provider.id, details=details)
        if response.status >= 500:
            return AIError("provider_unavailable", f"{provider.label} 服务暂时不可用", status_code=503, provider_id=provider.id, retryable=True, details=details)
        return AIError("provider_http_error", f"{provider.label} 返回错误（HTTP {response.status}）", status_code=502, provider_id=provider.id, details=details)

    def list_models(self, provider: ResolvedProvider) -> list[AIModelInfo]:
        raise NotImplementedError

    def chat(
        self,
        provider: ResolvedProvider,
        messages: list[AIChatMessage],
        system_prompt: str | None,
    ) -> ChatOutcome:
        raise NotImplementedError


class OpenAICompatibleAdapter(_AdapterBase):
    """Standard /v1/models and /v1/chat/completions, not vendor-specific."""

    def _root(self, provider: ResolvedProvider) -> str:
        base = provider.base_url.rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base.rstrip("/")

    def _headers(self, provider: ResolvedProvider) -> dict[str, str]:
        if not provider.api_key:
            raise AIError("missing_api_key", "尚未配置 API Key", status_code=400, provider_id=provider.id)
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Accept": "application/json",
            "User-Agent": "Hephaestus/2.0",
        }

    def _models_url(self, provider: ResolvedProvider) -> str:
        return f"{self._root(provider)}/models"

    def _chat_url(self, provider: ResolvedProvider) -> str:
        return f"{self._root(provider)}/chat/completions"

    def list_models(self, provider: ResolvedProvider) -> list[AIModelInfo]:
        data = self._request_json(provider, "GET", self._models_url(provider), headers=self._headers(provider))
        items = data.get("data")
        if not isinstance(items, list):
            raise AIError("invalid_provider_response", "模型列表缺少 data 字段", status_code=502, provider_id=provider.id)
        models: list[AIModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            details: dict[str, str] = {}
            if item.get("owned_by"):
                details["owned_by"] = str(item["owned_by"])
            models.append(AIModelInfo(id=model_id, name=model_id, details=details))
        return models

    def chat(
        self,
        provider: ResolvedProvider,
        messages: list[AIChatMessage],
        system_prompt: str | None,
    ) -> ChatOutcome:
        outgoing: list[dict[str, str]] = []
        if system_prompt:
            outgoing.append({"role": "system", "content": system_prompt})
        outgoing.extend({"role": message.role, "content": message.content} for message in messages)
        payload = {
            "model": provider.model,
            "messages": outgoing,
            "temperature": provider.params.temperature,
            "max_tokens": provider.params.max_tokens,
            "top_p": provider.params.top_p,
            "stream": False,
        }
        data = self._request_json(provider, "POST", self._chat_url(provider), headers=self._headers(provider), payload=payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIError("invalid_provider_response", "模型响应缺少 choices", status_code=502, provider_id=provider.id)
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise AIError("invalid_provider_response", "模型返回了空内容", status_code=502, provider_id=provider.id)
        usage_data = data.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            usage = AIChatUsage(
                prompt_tokens=usage_data.get("prompt_tokens"),
                completion_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            )
        return ChatOutcome(content=content, finish_reason=choices[0].get("finish_reason"), usage=usage)


class OllamaAdapter(_AdapterBase):
    """Local Ollama: /api/tags and /api/chat, desktop/web only."""

    def _root(self, provider: ResolvedProvider) -> str:
        base = provider.base_url.rstrip("/")
        for suffix in ("/api/tags", "/api/chat", "/api"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": "Hephaestus/2.0"}

    def list_models(self, provider: ResolvedProvider) -> list[AIModelInfo]:
        data = self._request_json(provider, "GET", f"{self._root(provider)}/api/tags", headers=self._headers())
        items = data.get("models")
        if not isinstance(items, list):
            raise AIError("invalid_provider_response", "Ollama 模型列表缺少 models 字段", status_code=502, provider_id=provider.id)
        models: list[AIModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name:
                continue
            size = item.get("size")
            details: dict[str, str] = {}
            for key in ("family", "parameter_size", "quantization_level"):
                if item.get(key):
                    details[key] = str(item[key])
            models.append(
                AIModelInfo(
                    id=name,
                    name=name,
                    size_bytes=int(size) if isinstance(size, int) and size >= 0 else None,
                    modified_at=str(item["modified_at"]) if item.get("modified_at") else None,
                    details=details,
                )
            )
        return models

    def chat(
        self,
        provider: ResolvedProvider,
        messages: list[AIChatMessage],
        system_prompt: str | None,
    ) -> ChatOutcome:
        installed = self.list_models(provider)
        if not any(model.id == provider.model for model in installed):
            raise AIError(
                "model_not_found",
                f"Ollama 未安装模型 {provider.model}",
                status_code=404,
                provider_id=provider.id,
                details={"available_models": [model.id for model in installed][:50]},
            )
        outgoing: list[dict[str, str]] = []
        if system_prompt:
            outgoing.append({"role": "system", "content": system_prompt})
        outgoing.extend({"role": message.role, "content": message.content} for message in messages)
        payload = {
            "model": provider.model,
            "messages": outgoing,
            "stream": False,
            "options": {
                "temperature": provider.params.temperature,
                "top_p": provider.params.top_p,
                "num_predict": provider.params.max_tokens,
            },
        }
        data = self._request_json(provider, "POST", f"{self._root(provider)}/api/chat", headers=self._headers(), payload=payload)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AIError("invalid_provider_response", "Ollama 返回了空内容", status_code=502, provider_id=provider.id)
        usage = None
        prompt_count = data.get("prompt_eval_count")
        eval_count = data.get("eval_count")
        if isinstance(prompt_count, int) or isinstance(eval_count, int):
            prompt_tokens = prompt_count if isinstance(prompt_count, int) else None
            completion_tokens = eval_count if isinstance(eval_count, int) else None
            total = None
            if prompt_tokens is not None and completion_tokens is not None:
                total = prompt_tokens + completion_tokens
            usage = AIChatUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total)
        return ChatOutcome(content=content, finish_reason=data.get("done_reason"), usage=usage)


def adapter_for(kind: str, transport: HttpTransport) -> _AdapterBase:
    if kind == "ollama":
        return OllamaAdapter(transport)
    if kind in OPENAI_COMPATIBLE_KINDS:
        return OpenAICompatibleAdapter(transport)
    raise AIError("unsupported_provider", f"暂不支持 {kind} 类型的 AI Provider", status_code=422)