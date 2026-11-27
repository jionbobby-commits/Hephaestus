"""C2 chat tests: capability auth, conversations, streaming, stop/regenerate, safety."""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.v2.ai.api import get_ai_secret_store, get_ai_transport
from app.v2.ai.capability import (
    CAPABILITY_HEADER,
    configure_capability_token,
    current_token,
    reset_for_tests,
)
from app.v2.ai.chat import ChatService
from app.v2.ai.errors import AIError
from app.v2.ai.secrets import InMemorySecretStore
from app.v2.ai.service import AIProviderService
from app.v2.ai.transport import (
    HttpResponse,
    HttpResponseStream,
    TransportConnectionError,
)
from app.v2.contracts import SendMessageRequest
from app.v2.dataport import SqlAlchemyDataPort
from app.v2.db import configure_sqlite, create_v2_db, get_v2_session
from app.v2.models import MessageV2

OPENAI_BASE = "http://127.0.0.1:8080/v1"
CHAT_URL = OPENAI_BASE + "/chat/completions"
CAP_TOKEN = "c2-test-capability-token-0123456789abcdef0123456789abcdef"
API_KEY = "sk-c2-secret-key-do-not-leak"


def _line(text: str, finish_reason=None) -> bytes:
    return (
        "data: "
        + json.dumps(
            {"choices": [{"delta": {"content": text}, "finish_reason": finish_reason}]},
            ensure_ascii=False,
        )
        + "\n"
    ).encode()


def _sse(chunks, usage=None, finish_reason="stop"):
    lines = []
    for text in chunks:
        lines.append(
            (
                "data: "
                + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]})
                + "\n"
            ).encode()
        )
    lines.append(
        (
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": finish_reason}],
                    "usage": usage or {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                }
            )
            + "\n"
        ).encode()
    )
    lines.append(b"data: [DONE]\n")
    return lines


class ChatTransport:
    def __init__(self) -> None:
        self.stream_routes: dict[str, object] = {}
        self.stream_calls: list[dict] = []
        self.calls: list[dict] = []

    def route_stream(self, lines, status: int = 200) -> None:
        self.stream_routes[CHAT_URL] = (status, lines)

    def request(self, method, url, *, headers, json_body, timeout, max_bytes, resolved_ips=None):
        self.calls.append({"method": method, "url": url, "json": json_body})
        return HttpResponse(status=404, headers={}, body=b'{"error":"not found"}')

    def stream(self, method, url, *, headers, json_body, timeout, max_bytes, resolved_ips=None):
        self.stream_calls.append(
            {"method": method, "url": url, "headers": headers, "json": json_body}
        )
        route = self.stream_routes.get(url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return HttpResponseStream(
                status=404,
                headers={},
                lines=iter([b'{"error":"not found"}']),
                close=lambda: None,
            )
        status, lines = route
        iterator = iter(lines) if not callable(lines) else lines()
        return HttpResponseStream(status=status, headers={}, lines=iterator, close=lambda: None)


def _provider_payload(kind: str = "openai") -> dict:
    return {
        "kind": kind,
        "label": "C2 测试 Provider",
        "base_url": OPENAI_BASE if kind == "openai" else "http://127.0.0.1:11434",
        "model": "gpt-test" if kind == "openai" else "llama-test",
        "api_key": API_KEY if kind == "openai" else None,
        "params": {"temperature": 0.2, "max_tokens": 64, "timeout_seconds": 5},
    }


@pytest.fixture()
def chat_env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    configure_sqlite(engine)
    create_v2_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = InMemorySecretStore()
    transport = ChatTransport()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override_session
    app.dependency_overrides[get_ai_secret_store] = lambda: store
    app.dependency_overrides[get_ai_transport] = lambda: transport
    configure_capability_token(CAP_TOKEN)
    headers = {CAPABILITY_HEADER: current_token()}
    try:
        with TestClient(app, headers=headers) as client:
            created = client.post("/api/v2/ai/providers", json=_provider_payload())
            assert created.status_code == 201, created.text
            provider = created.json()
            conversation = client.post(
                "/api/v2/ai/conversations",
                json={"provider_id": provider["id"], "title": "测试对话"},
            )
            assert conversation.status_code == 201, conversation.text
            yield {
                "client": client,
                "provider": provider,
                "conversation": conversation.json(),
                "transport": transport,
                "factory": factory,
                "store": store,
                "headers": headers,
                "engine": engine,
            }
    finally:
        app.dependency_overrides.pop(get_v2_session, None)
        app.dependency_overrides.pop(get_ai_secret_store, None)
        app.dependency_overrides.pop(get_ai_transport, None)
        reset_for_tests()
        engine.dispose()


def _service(env, platform: str = "desktop") -> ChatService:
    port = SqlAlchemyDataPort(env["factory"]())
    providers = AIProviderService(
        port,
        secret_store=env["store"],
        transport=env["transport"],
        platform=platform,
    )
    return ChatService(port, providers, session_factory=env["factory"], platform=platform)


def _send(client, conversation_id, content, **extra):
    return client.post(
        f"/api/v2/ai/conversations/{conversation_id}/messages",
        json={"content": content, **extra},
    )


def _sse_types(body: str) -> list[str]:
    kinds = []
    for line in body.splitlines():
        if line.startswith("data: "):
            kinds.append(json.loads(line[6:])["type"])
    return kinds


# ---------- C2.1 capability auth ----------


def test_missing_and_wrong_capability_are_rejected(chat_env):
    env = chat_env
    with TestClient(app) as bare:
        missing = bare.get("/api/v2/ai/providers")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "missing_capability"

    wrong = env["client"].get(
        "/api/v2/ai/providers", headers={CAPABILITY_HEADER: "x" * 64}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_capability"

    ok = env["client"].get("/api/v2/ai/providers")
    assert ok.status_code == 200


def test_cross_site_request_is_rejected_even_with_token(chat_env):
    response = chat_env["client"].get(
        "/api/v2/ai/conversations", headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"


def test_mobile_platform_is_rejected_for_ollama(chat_env):
    response = chat_env["client"].post(
        "/api/v2/ai/providers",
        json=_provider_payload("ollama"),
        headers={"X-Hephaestus-Platform": "mobile"},
    )
    assert response.status_code == 403
    assert "Ollama" in response.text


# ---------- C2.2 conversations ----------


def test_conversation_create_list_rename_archive_delete(chat_env):
    client = chat_env["client"]
    conversation = chat_env["conversation"]

    listed = client.get("/api/v2/ai/conversations")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == conversation["id"]

    renamed = client.patch(
        f"/api/v2/ai/conversations/{conversation['id']}",
        json={"title": "改名后的对话", "revision": conversation["revision"]},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "改名后的对话"
    assert renamed.json()["revision"] == conversation["revision"] + 1

    stale = client.patch(
        f"/api/v2/ai/conversations/{conversation['id']}",
        json={"title": "过期修改", "revision": conversation["revision"]},
    )
    assert stale.status_code == 409

    archived = client.patch(
        f"/api/v2/ai/conversations/{conversation['id']}", json={"archived": True}
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"]
    assert client.get("/api/v2/ai/conversations").json()["total"] == 0
    assert client.get("/api/v2/ai/conversations?include_archived=true").json()["total"] == 1

    blocked = _send(client, conversation["id"], "归档后不能发送")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "conversation_archived"

    deleted = client.delete(f"/api/v2/ai/conversations/{conversation['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v2/ai/conversations/{conversation['id']}").status_code == 404


def test_message_persistence_and_multi_turn_context(chat_env):
    env = chat_env
    transport = env["transport"]
    conversation_id = env["conversation"]["id"]
    transport.route_stream(_sse(["第一条"]))
    first = _send(env["client"], conversation_id, "第一问")
    assert first.status_code == 200, first.text
    assert first.json()["assistant_message"]["content"] == "第一条"

    transport.route_stream(_sse(["第二条"]))
    second = _send(env["client"], conversation_id, "第二问")
    assert second.status_code == 200, second.text

    history = env["client"].get(f"/api/v2/ai/conversations/{conversation_id}/messages").json()
    assert [m["role"] for m in history["items"]] == ["user", "assistant", "user", "assistant"]
    assert history["items"][0]["content"] == "第一问"
    assert history["items"][1]["content"] == "第一条"

    outgoing = transport.stream_calls[-1]["json"]["messages"]
    assert [m["role"] for m in outgoing] == ["user", "assistant", "user"]
    assert outgoing[0]["content"] == "第一问"
    assert outgoing[2]["content"] == "第二问"


def test_streaming_sse_events(chat_env):
    env = chat_env
    env["transport"].route_stream(_sse(["流式", "输出"]))
    response = _send(
        env["client"], env["conversation"]["id"], "请流式回答", stream=True
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    kinds = _sse_types(response.text)
    assert kinds[0] == "start"
    assert "delta" in kinds
    assert kinds[-1] == "done"
    done = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"done"' in line
    ][-1]
    assert done["reply"]["assistant_message"]["content"] == "流式输出"
    assert done["reply"]["assistant_message"]["status"] == "complete"


def test_duplicate_client_message_id_is_idempotent(chat_env):
    env = chat_env
    env["transport"].route_stream(_sse(["只生成一次"]))
    payload = {"content": "重复提交", "client_message_id": "client-msg-1"}
    first = env["client"].post(
        f"/api/v2/ai/conversations/{env['conversation']['id']}/messages", json=payload
    )
    second = env["client"].post(
        f"/api/v2/ai/conversations/{env['conversation']['id']}/messages", json=payload
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["assistant_message"]["id"] == second.json()["assistant_message"]["id"]
    assert len(env["transport"].stream_calls) == 1
    messages = env["client"].get(
        f"/api/v2/ai/conversations/{env['conversation']['id']}/messages"
    ).json()
    assert messages["total"] == 2


def test_duplicate_stream_request_reuses_finished_reply(chat_env):
    env = chat_env
    env["transport"].route_stream(_sse(["一次流式"]))
    payload = {"content": "重复流式提交", "client_message_id": "client-stream-1", "stream": True}
    first = _send(env["client"], env["conversation"]["id"], **payload)
    assert first.status_code == 200
    assert _sse_types(first.text)[-1] == "done"

    second = _send(env["client"], env["conversation"]["id"], **payload)
    assert second.status_code == 200
    kinds = _sse_types(second.text)
    assert kinds == ["done"]
    reply = [
        json.loads(line[6:])
        for line in second.text.splitlines()
        if line.startswith("data: ")
    ][0]["reply"]
    assert reply["assistant_message"]["content"] == "一次流式"
    assert len(env["transport"].stream_calls) == 1


def test_regenerate_replaces_the_same_assistant_message(chat_env):
    env = chat_env
    conversation_id = env["conversation"]["id"]
    env["transport"].route_stream(_sse(["旧回复"]))
    first = _send(env["client"], conversation_id, "重新生成测试")
    assistant_id = first.json()["assistant_message"]["id"]

    env["transport"].route_stream(_sse(["新回复"]))
    response = env["client"].post(
        f"/api/v2/ai/conversations/{conversation_id}/messages/{assistant_id}/regenerate",
        json={"message_id": assistant_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assistant_message"]["id"] == assistant_id
    assert response.json()["assistant_message"]["content"] == "新回复"
    messages = env["client"].get(f"/api/v2/ai/conversations/{conversation_id}/messages").json()
    assert messages["total"] == 2


def test_stop_generation_marks_message_stopped(chat_env):
    env = chat_env
    started = threading.Event()
    release = threading.Event()

    def slow_lines():
        yield _line("已生成")
        started.set()
        release.wait(5)
        yield _line("不应出现", "stop")

    env["transport"].route_stream(slow_lines)
    service = _service(env)
    stream = service.stream_message(
        env["conversation"]["id"], SendMessageRequest(content="停止测试", stream=True)
    )
    events: list[str] = []

    def consume():
        events.extend(stream)

    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    assert started.wait(3)
    result = service.stop(env["conversation"]["id"])
    release.set()
    worker.join(5)
    assert result.stopped is True
    assert result.message is not None and result.message.status == "stopped"
    joined = "".join(events)
    assert '"type":"stopped"' in joined
    assert "不应出现" not in joined


def test_concurrent_send_is_rejected(chat_env):
    env = chat_env
    started = threading.Event()
    release = threading.Event()

    def slow_lines():
        yield _line("占用")
        started.set()
        release.wait(5)
        yield b'data: [DONE]\n'

    env["transport"].route_stream(slow_lines)
    service = _service(env)
    stream = service.stream_message(
        env["conversation"]["id"], SendMessageRequest(content="占用会话", stream=True)
    )
    worker = threading.Thread(target=lambda: list(stream), daemon=True)
    worker.start()
    assert started.wait(3)
    with pytest.raises(AIError) as caught:
        service.send_message(
            env["conversation"]["id"], SendMessageRequest(content="并发写入")
        )
    assert caught.value.status_code == 409
    assert caught.value.code == "conversation_busy"
    release.set()
    worker.join(5)


# ---------- C2.3 failures, switching, limits ----------


def test_network_interruption_marks_message_error(chat_env):
    env = chat_env
    conversation_id = env["conversation"]["id"]

    def broken():
        yield _line("半截")
        raise TransportConnectionError("connection reset")

    env["transport"].route_stream(broken)
    response = _send(env["client"], conversation_id, "网络中断")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    messages = env["client"].get(f"/api/v2/ai/conversations/{conversation_id}/messages").json()
    assistant = messages["items"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["status"] == "error"
    assert assistant["error_code"] == "provider_unavailable"
    assert assistant["content"] == "半截"


def test_provider_unavailable_returns_unified_error(chat_env):
    env = chat_env
    env["transport"].route_stream([b'{"error":"down"}'], status=503)
    response = _send(env["client"], env["conversation"]["id"], "服务不可用")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "provider_unavailable"
    assert body["retryable"] is True


def test_model_switch_is_used_on_next_turn(chat_env):
    env = chat_env
    conversation_id = env["conversation"]["id"]
    env["transport"].route_stream(_sse(["模型一"]))
    assert _send(env["client"], conversation_id, "第一轮").status_code == 200

    patched = env["client"].patch(
        f"/api/v2/ai/conversations/{conversation_id}",
        json={"model": "gpt-switched"},
    )
    assert patched.status_code == 200
    env["transport"].route_stream(_sse(["模型二"]))
    assert _send(env["client"], conversation_id, "第二轮").status_code == 200
    assert env["transport"].stream_calls[-1]["json"]["model"] == "gpt-switched"


def test_context_is_bounded_by_messages_and_characters(chat_env):
    env = chat_env
    port = SqlAlchemyDataPort(env["factory"]())
    conversation_id = env["conversation"]["id"]
    for index in range(40):
        role = "user" if index % 2 == 0 else "assistant"
        port.append_message(conversation_id, role=role, content=f"{index:02d}-" + "x" * 1000)
    env["transport"].route_stream(_sse(["有界"]))
    response = _send(env["client"], conversation_id, "上下文测试")
    assert response.status_code == 200
    outgoing = env["transport"].stream_calls[-1]["json"]["messages"]
    assert len(outgoing) <= 30
    assert sum(len(item["content"]) for item in outgoing) <= 24_000
    assert outgoing[-1]["content"] == "上下文测试"


def test_long_system_prompt_still_hard_caps_context(chat_env):
    env = chat_env
    created = env["client"].post(
        "/api/v2/ai/conversations",
        json={
            "provider_id": env["provider"]["id"],
            "title": "长上下文",
            "system_prompt": "s" * 20_000,
        },
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    env["transport"].route_stream(_sse(["受限回复"]))
    response = _send(env["client"], conversation_id, "u" * 20_000)
    assert response.status_code == 200, response.text
    call = env["transport"].stream_calls[-1]["json"]
    assert sum(len(item["content"]) for item in call["messages"]) <= 24_000
    assert call["messages"][-1]["role"] == "user"
    assert len(call["messages"][-1]["content"]) <= 4_000


def test_stale_streaming_placeholder_recovers_as_error(chat_env):
    env = chat_env
    conversation_id = env["conversation"]["id"]
    env["transport"].route_stream(_sse(["正常"]))
    reply = _send(env["client"], conversation_id, "崩溃恢复测试")
    assert reply.status_code == 200
    assistant_id = reply.json()["assistant_message"]["id"]

    with env["factory"]() as session:
        session.execute(
            update(MessageV2)
            .where(MessageV2.id == assistant_id)
            .values(status="streaming", updated_at="2000-01-01T00:00:00.000Z")
        )
        session.commit()

    messages = env["client"].get(
        f"/api/v2/ai/conversations/{conversation_id}/messages"
    ).json()
    assistant = messages["items"][-1]
    assert assistant["status"] == "error"
    assert assistant["error_code"] == "generation_interrupted"
    assert assistant["content"] == "正常"


def test_restart_recovery_loads_conversation_and_messages(chat_env):
    env = chat_env
    conversation_id = env["conversation"]["id"]
    env["transport"].route_stream(_sse(["重启后还在"]))
    assert _send(env["client"], conversation_id, "持久化测试").status_code == 200
    env["client"].close()

    with TestClient(app, headers=env["headers"]) as restarted:
        detail = restarted.get(f"/api/v2/ai/conversations/{conversation_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["conversation"]["id"] == conversation_id
        assert body["messages"][0]["content"] == "持久化测试"
        assert body["messages"][1]["content"] == "重启后还在"


def test_token_and_api_key_never_leak(chat_env, caplog):
    env = chat_env
    caplog.set_level(logging.DEBUG)
    env["transport"].route_stream(_sse(["安全"]))
    response = _send(env["client"], env["conversation"]["id"], "安全检查")
    assert response.status_code == 200
    provider_list = env["client"].get("/api/v2/ai/providers").text
    for text in (response.text, provider_list, caplog.text):
        assert API_KEY not in text
        assert CAP_TOKEN not in text
    assert '"api_key"' not in provider_list


def test_legacy_routes_remain_available(chat_env):
    client = chat_env["client"]
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/state").status_code == 200
    assert client.get("/notes").status_code == 200
    assert client.get("/api/v2/status").status_code == 200


def test_unknown_conversation_returns_unified_404(chat_env):
    response = _send(chat_env["client"], "does-not-exist", "hello")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_error_uses_unified_ai_envelope(chat_env):
    response = chat_env["client"].post(
        "/api/v2/ai/conversations", json={"title": "缺少 provider_id"}
    )
    assert response.status_code == 422
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["details"]["errors"]


def test_dependency_error_uses_unified_ai_envelope(chat_env):
    response = chat_env["client"].get(
        "/api/v2/ai/conversations",
        headers={"X-Hephaestus-Platform": "robot"},
    )
    assert response.status_code == 422
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "invalid_request"
    assert "X-Hephaestus-Platform" in body["error"]["message"]
