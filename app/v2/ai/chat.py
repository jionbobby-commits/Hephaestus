"""C2 conversation engine: bounded context, streaming, stop and regenerate.

The engine never talks provider protocols itself. It resolves a provider through
AIProviderService once per turn, then consumes the adapter's unified stream.
"""
from __future__ import annotations

import json
import logging
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from app.v2.ai.adapters import ResolvedProvider
from app.v2.ai.errors import AIError
from app.v2.ai.service import AIProviderService
from app.v2.contracts import (
    AIChatMessage,
    AIChatUsage,
    ChatReply,
    ConversationRead,
    MessageRead,
    RegenerateRequest,
    SendMessageRequest,
    StopGenerationResult,
)
from app.v2.dataport import NotFoundError, SqlAlchemyDataPort

logger = logging.getLogger("hephaestus.ai.chat")

MAX_ASSISTANT_CHARS = 20_000
MAX_CONTEXT_CHARS = 24_000
MAX_CONTEXT_MESSAGES = 30


@dataclass
class _Turn:
    conversation_id: str
    user_message: MessageRead
    assistant_message: MessageRead
    provider: ResolvedProvider | None
    adapter: object | None
    system_prompt: str | None
    lock: threading.Lock
    idempotent: bool = False


class ChatService:
    def __init__(
        self,
        port: SqlAlchemyDataPort,
        providers: AIProviderService,
        *,
        session_factory: Callable[[], Session] | None = None,
        platform: str = "web",
    ) -> None:
        self.port = port
        self.providers = providers
        self.session_factory = session_factory
        self.platform = platform
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._active: dict[str, tuple[str, threading.Event]] = {}
        self._active_guard = threading.Lock()

    # ---------- conversations ----------

    def create_conversation(self, payload) -> ConversationRead:
        return self.port.create_conversation(payload, model=payload.model or "")

    def list_conversations(self, page: int, page_size: int, include_archived: bool):
        return self.port.list_conversations(
            page=page, page_size=page_size, include_archived=include_archived
        )

    def get_conversation(self, conversation_id: str) -> ConversationRead:
        return self.port.get_conversation(conversation_id)

    def detail(self, conversation_id: str, page: int, page_size: int):
        conversation = self.port.get_conversation(conversation_id)
        self.port.recover_stale_messages(conversation_id)
        messages = self.port.list_messages(conversation_id, page=page, page_size=page_size)
        return conversation, messages

    def list_messages(self, conversation_id: str, page: int, page_size: int):
        self.port.get_conversation(conversation_id)
        self.port.recover_stale_messages(conversation_id)
        return self.port.list_messages(conversation_id, page=page, page_size=page_size)

    def update_conversation(self, conversation_id: str, payload):
        return self.port.update_conversation(conversation_id, payload)

    def delete_conversation(self, conversation_id: str) -> None:
        self.port.delete_conversation(conversation_id)

    # ---------- send / regenerate ----------

    def send_message(self, conversation_id: str, payload: SendMessageRequest) -> ChatReply:
        turn = self._begin_send(conversation_id, payload)
        try:
            if turn.idempotent:
                return self._reply(self.port, turn, turn.assistant_message)
            return self._run_sync(turn)
        finally:
            self._release(turn)

    def stream_message(self, conversation_id: str, payload: SendMessageRequest) -> Iterator[str]:
        turn = self._begin_send(conversation_id, payload)
        result = self._stream(turn)
        weakref.finalize(result, self._release, turn)
        return result

    def regenerate(self, conversation_id: str, payload: RegenerateRequest) -> ChatReply:
        turn = self._begin_regenerate(conversation_id, payload.message_id)
        try:
            return self._run_sync(turn)
        finally:
            self._release(turn)

    def stream_regenerate(self, conversation_id: str, payload: RegenerateRequest) -> Iterator[str]:
        turn = self._begin_regenerate(conversation_id, payload.message_id)
        result = self._stream(turn)
        weakref.finalize(result, self._release, turn)
        return result

    def stop(self, conversation_id: str, message_id: str | None = None) -> StopGenerationResult:
        conversation = self.port.get_conversation(conversation_id)
        target: MessageRead | None = None
        if message_id:
            target = self.port.get_message(message_id)
            if target.conversation_id != conversation.id:
                raise NotFoundError(f"消息不存在: {message_id}")
        else:
            with self._active_guard:
                for active_id, (active_conversation, _event) in self._active.items():
                    if active_conversation == conversation.id:
                        target = self.port.get_message(active_id)
                        break
            if target is None:
                messages = self.port.list_messages(conversation.id, page=1, page_size=200)
                for item in reversed(messages.items):
                    if item.role == "assistant" and item.status in {"pending", "streaming"}:
                        target = item
                        break
        if target is None or target.role != "assistant":
            return StopGenerationResult(stopped=False, message=target)
        event = self._event_for(target.id)
        if event is not None:
            event.set()
        if target.status in {"pending", "streaming"}:
            updated = self.port.update_message(target.id, status="stopped")
            return StopGenerationResult(stopped=True, message=updated)
        return StopGenerationResult(stopped=False, message=target)

    # ---------- turn setup ----------

    def _begin_send(self, conversation_id: str, payload: SendMessageRequest) -> _Turn:
        lock = self._lock_for(conversation_id)
        if not lock.acquire(blocking=False):
            raise AIError(
                "conversation_busy",
                "该对话正在生成回复，请等待完成或先停止生成",
                status_code=409,
                retryable=True,
            )
        try:
            conversation = self.port.get_conversation(conversation_id)
            if conversation.archived_at:
                raise AIError("conversation_archived", "对话已归档，无法发送消息", status_code=409)
            client_id = payload.client_message_id
            if client_id:
                existing = self.port.find_message_by_client_id(conversation_id, client_id)
                if existing is not None:
                    assistant = self.port.next_message(conversation_id, existing.sequence + 1)
                    if assistant is not None and assistant.role == "assistant" and assistant.status in {
                        "complete",
                        "stopped",
                        "error",
                    }:
                        return _Turn(
                            conversation_id=conversation_id,
                            user_message=existing,
                            assistant_message=assistant,
                            provider=None,
                            adapter=None,
                            system_prompt=conversation.system_prompt,
                            lock=lock,
                            idempotent=True,
                        )
                    if assistant is None or assistant.role != "assistant":
                        assistant = self.port.append_message(
                            conversation_id, role="assistant", content="", status="pending"
                        )
                    provider, adapter, system_prompt = self._resolve(conversation)
                    return _Turn(
                        conversation_id=conversation_id,
                        user_message=existing,
                        assistant_message=assistant,
                        provider=provider,
                        adapter=adapter,
                        system_prompt=system_prompt,
                        lock=lock,
                    )
            user = self.port.append_message(
                conversation_id,
                role="user",
                content=payload.content.strip(),
                client_id=client_id,
            )
            assistant = self.port.append_message(
                conversation_id, role="assistant", content="", status="pending"
            )
            try:
                provider, adapter, system_prompt = self._resolve(conversation)
            except AIError as exc:
                self.port.update_message(
                    assistant.id, status="error", error_code=exc.code
                )
                raise
            return _Turn(
                conversation_id=conversation_id,
                user_message=user,
                assistant_message=assistant,
                provider=provider,
                adapter=adapter,
                system_prompt=system_prompt,
                lock=lock,
            )
        except Exception:
            lock.release()
            raise

    def _begin_regenerate(self, conversation_id: str, message_id: str) -> _Turn:
        lock = self._lock_for(conversation_id)
        if not lock.acquire(blocking=False):
            raise AIError(
                "conversation_busy",
                "该对话正在生成回复，请等待完成或先停止生成",
                status_code=409,
                retryable=True,
            )
        try:
            conversation = self.port.get_conversation(conversation_id)
            if conversation.archived_at:
                raise AIError("conversation_archived", "对话已归档，无法重新生成", status_code=409)
            target = self.port.get_message(message_id)
            if target.conversation_id != conversation.id:
                raise NotFoundError(f"消息不存在: {message_id}")
            if target.role != "assistant":
                raise AIError("invalid_message", "只能重新生成 AI 回复", status_code=422)
            if target.status in {"pending", "streaming"}:
                raise AIError("message_busy", "该回复仍在生成中", status_code=409)
            user = self.port.last_user_before(conversation.id, target.sequence)
            if user is None:
                raise AIError("invalid_message", "找不到对应的用户消息", status_code=422)
            reset = self.port.update_message(
                target.id, content="", status="pending", error_code=None
            )
            try:
                provider, adapter, system_prompt = self._resolve(conversation)
            except AIError as exc:
                self.port.update_message(reset.id, status="error", error_code=exc.code)
                raise
            return _Turn(
                conversation_id=conversation_id,
                user_message=user,
                assistant_message=reset,
                provider=provider,
                adapter=adapter,
                system_prompt=system_prompt,
                lock=lock,
            )
        except Exception:
            lock.release()
            raise

    def _resolve(self, conversation: ConversationRead):
        if not conversation.provider_id:
            raise AIError("provider_not_found", "对话未绑定 AI 配置", status_code=422)
        row, provider, adapter = self.providers.resolve_for_chat(
            conversation.provider_id, conversation.model or None
        )
        return provider, adapter, conversation.system_prompt

    # ---------- generation ----------

    def _run_sync(self, turn: _Turn) -> ChatReply:
        if turn.provider is None or turn.adapter is None:
            return self._reply(self.port, turn, turn.assistant_message)
        with self._port_scope() as port:
            assistant = port.get_message(turn.assistant_message.id)
            if assistant.status == "stopped" or assistant.id in self._active_ids():
                return self._reply(port, turn, assistant)
            context = self._context(port, turn)
            assistant = port.update_message(assistant.id, status="streaming")
            content: list[str] = []
            total_chars = 0
            finish_reason = None
            usage: AIChatUsage | None = None
            cancel = self._register(turn)
            try:
                with self.providers.call_slot():
                    for delta in turn.adapter.chat_stream(
                        turn.provider, context, turn.system_prompt, cancel_event=cancel
                    ):
                        if cancel.is_set():
                            break
                        if delta.text:
                            content.append(delta.text)
                            total_chars += len(delta.text)
                            if total_chars > MAX_ASSISTANT_CHARS:
                                raise AIError(
                                    "invalid_provider_response",
                                    "模型响应超过长度上限",
                                    status_code=502,
                                    provider_id=turn.provider.id,
                                )
                            assistant = port.update_message(
                                assistant.id, content="".join(content)
                            )
                        if delta.finish_reason:
                            finish_reason = delta.finish_reason
                        if delta.usage:
                            usage = delta.usage
                final_status = "stopped" if cancel.is_set() else "complete"
                assistant = port.update_message(assistant.id, status=final_status)
                return self._reply(
                    port, turn, assistant, finish_reason=finish_reason, usage=usage
                )
            except AIError as exc:
                assistant = port.update_message(
                    assistant.id,
                    content="".join(content),
                    status="error",
                    error_code=exc.code,
                )
                raise
            except Exception as exc:  # noqa: BLE001 - provider boundary
                logger.exception(
                    "AI chat failed conversation=%s message=%s",
                    turn.conversation_id,
                    turn.assistant_message.id,
                )
                error = AIError(
                    "provider_unavailable",
                    "生成回复失败，请稍后重试",
                    status_code=503,
                    provider_id=turn.provider.id,
                    retryable=True,
                    details={"reason": type(exc).__name__},
                )
                port.update_message(
                    assistant.id,
                    content="".join(content),
                    status="error",
                    error_code=error.code,
                )
                raise error from exc
            finally:
                self._unregister(turn)

    def _stream(self, turn: _Turn) -> Iterator[str]:
        def events() -> Iterator[str]:
            try:
                with self._port_scope() as port:
                    if turn.provider is None or turn.adapter is None:
                        yield _sse(
                            {
                                "type": "done",
                                "reply": self._reply(
                                    port, turn, turn.assistant_message
                                ).model_dump(mode="json"),
                            }
                        )
                        return
                    assistant = port.get_message(turn.assistant_message.id)
                    if assistant.status == "stopped":
                        yield _sse(
                            {
                                "type": "stopped",
                                "message": assistant.model_dump(mode="json"),
                            }
                        )
                        return
                    context = self._context(port, turn)
                    assistant = port.update_message(assistant.id, status="streaming")
                    yield _sse(
                        {
                            "type": "start",
                            "conversation_id": turn.conversation_id,
                            "user_message": turn.user_message.model_dump(mode="json"),
                            "assistant_message": assistant.model_dump(mode="json"),
                        }
                    )
                    content: list[str] = []
                    total_chars = 0
                    finish_reason = None
                    usage: AIChatUsage | None = None
                    cancel = self._register(turn)
                    try:
                        with self.providers.call_slot():
                            for delta in turn.adapter.chat_stream(
                                turn.provider, context, turn.system_prompt, cancel_event=cancel
                            ):
                                if cancel.is_set():
                                    break
                                if delta.text:
                                    content.append(delta.text)
                                    total_chars += len(delta.text)
                                    if total_chars > MAX_ASSISTANT_CHARS:
                                        raise AIError(
                                            "invalid_provider_response",
                                            "模型响应超过长度上限",
                                            status_code=502,
                                            provider_id=turn.provider.id,
                                        )
                                    assistant = port.update_message(
                                        assistant.id, content="".join(content)
                                    )
                                    yield _sse(
                                        {
                                            "type": "delta",
                                            "message_id": assistant.id,
                                            "text": delta.text,
                                        }
                                    )
                                if delta.finish_reason:
                                    finish_reason = delta.finish_reason
                                if delta.usage:
                                    usage = delta.usage
                        if cancel.is_set():
                            assistant = port.update_message(
                                assistant.id, content="".join(content), status="stopped"
                            )
                            yield _sse(
                                {
                                    "type": "stopped",
                                    "message": assistant.model_dump(mode="json"),
                                }
                            )
                            return
                        assistant = port.update_message(
                            assistant.id, content="".join(content), status="complete"
                        )
                        reply = self._reply(
                            port,
                            turn,
                            assistant,
                            finish_reason=finish_reason,
                            usage=usage,
                        )
                        yield _sse({"type": "done", "reply": reply.model_dump(mode="json")})
                    except AIError as exc:
                        assistant = port.update_message(
                            assistant.id,
                            content="".join(content),
                            status="error",
                            error_code=exc.code,
                        )
                        yield _sse(
                            {
                                "type": "error",
                                "error": exc.to_response().model_dump(mode="json")["error"],
                                "message": assistant.model_dump(mode="json"),
                                "retryable": exc.retryable,
                            }
                        )
                    except GeneratorExit:
                        port.update_message(
                            assistant.id, content="".join(content), status="stopped"
                        )
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "AI chat stream failed conversation=%s message=%s",
                            turn.conversation_id,
                            turn.assistant_message.id,
                        )
                        error = AIError(
                            "provider_unavailable",
                            "生成回复失败，请稍后重试",
                            status_code=503,
                            provider_id=turn.provider.id,
                            retryable=True,
                            details={"reason": type(exc).__name__},
                        )
                        assistant = port.update_message(
                            assistant.id,
                            content="".join(content),
                            status="error",
                            error_code=error.code,
                        )
                        yield _sse(
                            {
                                "type": "error",
                                "error": error.to_response().model_dump(mode="json")["error"],
                                "message": assistant.model_dump(mode="json"),
                                "retryable": True,
                            }
                        )
                    finally:
                        self._unregister(turn)
            finally:
                self._release(turn)

        return events()

    def _context(self, port: SqlAlchemyDataPort, turn: _Turn) -> list[AIChatMessage]:
        system_chars = len(turn.system_prompt or "")
        budget = max(2_000, MAX_CONTEXT_CHARS - system_chars)
        history = port.context_messages(
            turn.conversation_id,
            before_sequence=turn.assistant_message.sequence,
            limit=MAX_CONTEXT_MESSAGES,
            char_budget=budget,
        )
        return [
            AIChatMessage(role=item.role, content=item.content)
            for item in history
            if item.role in {"user", "assistant"} and item.content
        ]

    def _reply(
        self,
        port: SqlAlchemyDataPort,
        turn: _Turn,
        assistant: MessageRead,
        *,
        finish_reason: str | None = None,
        usage: AIChatUsage | None = None,
    ) -> ChatReply:
        return ChatReply(
            conversation=port.get_conversation(turn.conversation_id),
            user_message=turn.user_message,
            assistant_message=assistant,
            finish_reason=finish_reason,
            usage=usage,
        )

    # ---------- active generation registry ----------

    def _lock_for(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(conversation_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[conversation_id] = lock
            return lock

    def _register(self, turn: _Turn) -> threading.Event:
        event = threading.Event()
        with self._active_guard:
            self._active[turn.assistant_message.id] = (turn.conversation_id, event)
        return event

    def _unregister(self, turn: _Turn) -> None:
        with self._active_guard:
            self._active.pop(turn.assistant_message.id, None)

    def _event_for(self, message_id: str) -> threading.Event | None:
        with self._active_guard:
            found = self._active.get(message_id)
            return found[1] if found else None

    def _active_ids(self) -> set[str]:
        with self._active_guard:
            return set(self._active.keys())

    def _release(self, turn: _Turn) -> None:
        try:
            turn.lock.release()
        except RuntimeError:
            pass

    @contextmanager
    def _port_scope(self):
        if self.session_factory is None:
            yield self.port
            return
        session = self.session_factory()
        try:
            yield SqlAlchemyDataPort(session)
        finally:
            session.close()


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"