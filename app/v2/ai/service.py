"""AI provider configuration, secret lifecycle and use-case orchestration."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.v2.ai.adapters import ResolvedProvider, adapter_for
from app.v2.ai.errors import AIError
from app.v2.ai.secrets import SecretStore, SecretStoreError, default_secret_store
from app.v2.ai.security import (
    SUPPORTED_KINDS,
    new_key_ref,
    provider_label,
    provider_model,
    resolve_base_url,
    validate_base_url,
)
from app.v2.ai.transport import HttpTransport, default_transport
from app.v2.contracts import (
    AIChatRequest,
    AIChatResult,
    AIConnectionTest,
    AIModelList,
    AIProviderConfigCreate,
    AIProviderConfigRead,
    AIProviderConfigUpdate,
)
from app.v2.dataport import NotFoundError, SqlAlchemyDataPort

logger = logging.getLogger("hephaestus.ai")

# Outbound calls are capped per process. A local client cannot exhaust the
# thread pool or open an unbounded number of provider connections.
_MAX_CONCURRENT_CALLS = 4
_CALL_SLOTS = threading.BoundedSemaphore(_MAX_CONCURRENT_CALLS)


class AIProviderService:
    def __init__(
        self,
        port: SqlAlchemyDataPort,
        *,
        secret_store: SecretStore | None = None,
        transport: HttpTransport | None = None,
        platform: str = "web",
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self.port = port
        self.secret_store = secret_store or default_secret_store()
        self.transport = transport or default_transport()
        self.platform = self._platform(platform)
        self.max_response_bytes = max_response_bytes

    # ---------- reads ----------

    def list_providers(self) -> list[AIProviderConfigRead]:
        return [self.port.provider_public(row, has_key=bool(row.key_ref)) for row in self.port.list_ai_provider_rows()]

    def get_provider(self, provider_id: str) -> AIProviderConfigRead:
        row = self._row(provider_id)
        return self.port.provider_public(row, has_key=bool(row.key_ref))

    # ---------- config writes ----------

    def create_provider(self, payload: AIProviderConfigCreate) -> AIProviderConfigRead:
        label, base_url, model = self._validate(payload.kind, payload.label, payload.base_url, payload.model)
        if payload.is_default and not payload.enabled:
            raise AIError("invalid_request", "禁用的配置不能设为默认模型", status_code=422)
        # The server owns secret locators. Older clients may still send
        # key_ref, but it must never bind a provider to an arbitrary store key.
        normalized = payload.model_copy(
            update={"label": label, "base_url": base_url, "model": model, "key_ref": None}
        )
        key_ref = None
        if payload.api_key is not None:
            key_ref = new_key_ref()
            self._store_secret(key_ref, self._secret_text(payload.api_key))
        created_id: str | None = None
        try:
            public = self.port.create_ai_provider(normalized, key_ref=key_ref)
            created_id = public.id
            rows = self.port.list_ai_provider_rows()
            current = self._current_default_id(rows)
            default_id = current or (public.id if payload.enabled else None)
            if payload.is_default:
                default_id = public.id
            self.port.set_ai_defaults(default_id)
            return self.get_provider(public.id)
        except Exception:
            if key_ref:
                self._delete_secret_quietly(key_ref)
            if created_id is not None:
                try:
                    self.port.delete_ai_provider(created_id)
                except Exception:
                    logger.warning("AI provider create cleanup failed provider=%s", created_id)
            raise

    def update_provider(self, provider_id: str, payload: AIProviderConfigUpdate) -> AIProviderConfigRead:
        row = self._row(provider_id)
        before = self.port.provider_public(row, has_key=bool(row.key_ref))
        fields = payload.model_fields_set
        kind = payload.kind if "kind" in fields else row.kind
        label = payload.label if "label" in fields else row.label
        base_url = payload.base_url if "base_url" in fields else row.base_url
        model = payload.model if "model" in fields else row.model
        enabled = payload.enabled if "enabled" in fields else before.enabled
        if payload.is_default is True and not enabled:
            raise AIError("invalid_request", "禁用的配置不能设为默认模型", status_code=422)
        label, base_url, model = self._validate(kind, label, base_url, model)

        key_ref: str | None | object = _NO_KEY_CHANGE
        old_ref = row.key_ref
        old_secret: str | None = None
        secret_changed = False
        if "api_key" in fields and payload.api_key is not None:
            if old_ref:
                old_secret = self._get_secret(old_ref)
            key_ref = old_ref or new_key_ref()
            self._store_secret(key_ref, self._secret_text(payload.api_key))
            secret_changed = True
        elif payload.clear_api_key and "clear_api_key" in fields:
            if old_ref:
                old_secret = self._get_secret(old_ref)
                self._delete_secret(old_ref)
            key_ref = None
            secret_changed = True

        update_payload = payload.model_copy(update={"label": label, "base_url": base_url, "model": model})
        try:
            if key_ref is _NO_KEY_CHANGE:
                public = self.port.update_ai_provider(provider_id, update_payload)
            else:
                public = self.port.update_ai_provider(provider_id, update_payload, key_ref=key_ref)
        except Exception:
            if secret_changed:
                self._restore_secret(old_ref, old_secret, key_ref if key_ref is not _NO_KEY_CHANGE else None)
            raise

        rows = self.port.list_ai_provider_rows()
        current = self._current_default_id(rows)
        if payload.is_default is True:
            default_id = provider_id
        elif payload.is_default is False and current == provider_id:
            default_id = self._first_enabled_id(rows, exclude=provider_id)
        elif enabled is False and current == provider_id:
            default_id = self._first_enabled_id(rows, exclude=provider_id)
        elif current is None and enabled:
            default_id = provider_id
        else:
            default_id = current
        self.port.set_ai_defaults(default_id)
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: str) -> None:
        row = self._row(provider_id)
        old_ref = row.key_ref
        old_secret = self._get_secret(old_ref) if old_ref else None
        if old_ref:
            self._delete_secret(old_ref)
        try:
            self.port.delete_ai_provider(provider_id)
        except Exception:
            if old_ref and old_secret is not None:
                try:
                    self.secret_store.set(old_ref, old_secret)
                except SecretStoreError:
                    logger.error("AI secret restore failed after delete error provider=%s", provider_id)
            raise
        rows = self.port.list_ai_provider_rows()
        current = self._current_default_id(rows)
        self.port.set_ai_defaults(current or self._first_enabled_id(rows))

    # ---------- provider use ----------

    def list_models(self, provider_id: str) -> AIModelList:
        row, provider, adapter = self._resolve_for_use(provider_id)
        models = self._call(lambda: adapter.list_models(provider))
        return AIModelList(provider_id=row.id, kind=row.kind, models=models)

    def test_connection(self, provider_id: str) -> AIConnectionTest:
        row, provider, adapter = self._resolve_for_use(provider_id)
        started = time.monotonic()
        models = self._call(lambda: adapter.list_models(provider))
        latency = int((time.monotonic() - started) * 1000)
        return AIConnectionTest(
            ok=True,
            provider_id=row.id,
            kind=row.kind,
            model=row.model,
            model_count=len(models),
            latency_ms=latency,
            message=f"连接成功，发现 {len(models)} 个模型",
        )

    def chat(self, request: AIChatRequest) -> AIChatResult:
        row, provider, adapter = self._resolve_for_use(request.provider_id)
        started = time.monotonic()
        outcome = self._call(
            lambda: adapter.chat(provider, request.messages, request.system_prompt)
        )
        latency = int((time.monotonic() - started) * 1000)
        if len(outcome.content) > 20_000:
            raise AIError("invalid_provider_response", "模型响应超过长度上限", status_code=502, provider_id=row.id)
        from app.v2.contracts import AIChatMessage

        logger.info("AI chat provider=%s kind=%s model=%s", row.id, row.kind, row.model)
        return AIChatResult(
            provider_id=row.id,
            model=row.model,
            message=AIChatMessage(role="assistant", content=outcome.content),
            finish_reason=outcome.finish_reason,
            usage=outcome.usage,
            latency_ms=latency,
        )

    # ---------- helpers ----------

    def _row(self, provider_id: str):
        try:
            return self.port.get_ai_provider_row(provider_id)
        except NotFoundError as exc:
            raise AIError("provider_not_found", "AI 配置不存在", status_code=404, provider_id=provider_id) from exc

    def _resolve_for_use(self, provider_id: str):
        row = self._row(provider_id)
        public = self.port.provider_public(row, has_key=bool(row.key_ref))
        if not public.enabled:
            raise AIError("provider_disabled", "该 AI 配置已禁用", status_code=409, provider_id=row.id)
        if self.platform == "mobile" and row.kind == "ollama":
            raise AIError("mobile_ollama_forbidden", "移动端不支持 Ollama，请使用在线 API", status_code=403, provider_id=row.id)
        if row.kind not in SUPPORTED_KINDS:
            raise AIError("unsupported_provider", f"暂不支持 {row.kind} 类型的 AI Provider", status_code=422, provider_id=row.id)
        label = provider_label(row.label)
        base_url, resolved_ips = resolve_base_url(
            row.kind, row.base_url, platform=self.platform
        )
        model = provider_model(row.model)
        api_key = None
        if row.kind != "ollama":
            if not row.key_ref:
                raise AIError("missing_api_key", "尚未配置 API Key", status_code=400, provider_id=row.id)
            api_key = self._get_secret(row.key_ref)
            if not api_key:
                raise AIError("missing_api_key", "API Key 不存在，请重新填写", status_code=400, provider_id=row.id)
        provider = ResolvedProvider(
            id=row.id,
            kind=row.kind,
            label=label,
            base_url=base_url,
            model=model,
            params=public.params,
            api_key=api_key,
            resolved_ips=tuple(resolved_ips),
        )
        return row, provider, adapter_for(row.kind, self.transport)

    def _validate(self, kind: str, label: str, base_url: str, model: str) -> tuple[str, str, str]:
        if kind not in SUPPORTED_KINDS:
            raise AIError("unsupported_provider", f"C1 暂不支持 {kind} 类型的 AI Provider", status_code=422)
        clean_label = provider_label(label)
        clean_model = provider_model(model)
        clean_base = validate_base_url(kind, base_url, platform=self.platform)
        return clean_label, clean_base, clean_model

    @staticmethod
    def _call(action):
        if not _CALL_SLOTS.acquire(blocking=False):
            raise AIError(
                "too_many_requests",
                "AI 请求并发过高，请稍后再试",
                status_code=429,
                retryable=True,
            )
        try:
            return action()
        finally:
            _CALL_SLOTS.release()

    @staticmethod
    def _platform(value: str) -> str:
        platform = (value or "web").strip().lower()
        if platform not in {"desktop", "web", "mobile"}:
            raise AIError("invalid_request", "未知的客户端平台", status_code=422)
        return platform

    @staticmethod
    def _secret_text(secret: Any) -> str:
        value = secret.get_secret_value().strip() if hasattr(secret, "get_secret_value") else str(secret).strip()
        if not value:
            raise AIError("invalid_request", "API Key 不能为空", status_code=422)
        if len(value) > 8192:
            raise AIError("invalid_request", "API Key 过长", status_code=422)
        return value

    def _store_secret(self, ref: str, secret: str) -> None:
        try:
            self.secret_store.set(ref, secret)
        except SecretStoreError as exc:
            raise AIError("secret_store_unavailable", "系统密钥存储不可用，API Key 未保存", status_code=503) from exc

    def _get_secret(self, ref: str) -> str | None:
        try:
            return self.secret_store.get(ref)
        except SecretStoreError as exc:
            raise AIError("secret_store_unavailable", "系统密钥存储不可用，无法读取 API Key", status_code=503) from exc

    def _delete_secret(self, ref: str) -> None:
        try:
            self.secret_store.delete(ref)
        except SecretStoreError as exc:
            raise AIError("secret_store_unavailable", "系统密钥存储不可用，无法删除 API Key", status_code=503) from exc

    def _delete_secret_quietly(self, ref: str) -> None:
        try:
            self.secret_store.delete(ref)
        except SecretStoreError:
            logger.warning("AI secret cleanup failed ref=%s", ref)

    def _restore_secret(self, old_ref: str | None, old_secret: str | None, new_ref: str | None) -> None:
        try:
            if old_ref and old_secret is not None:
                self.secret_store.set(old_ref, old_secret)
            elif new_ref:
                self.secret_store.delete(new_ref)
        except SecretStoreError:
            logger.error("AI secret rollback failed")

    @classmethod
    def _current_default_id(cls, rows) -> str | None:
        for row in rows:
            _extra, enabled, is_default, _params = SqlAlchemyDataPort._provider_meta(row)
            if is_default and enabled:
                return row.id
        return None

    @classmethod
    def _first_enabled_id(cls, rows, *, exclude: str | None = None) -> str | None:
        for row in rows:
            _extra, enabled, _is_default, _params = SqlAlchemyDataPort._provider_meta(row)
            if enabled and row.id != exclude:
                return row.id
        return None


_NO_KEY_CHANGE = object()