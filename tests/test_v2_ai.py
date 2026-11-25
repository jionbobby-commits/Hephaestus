"""C1 AI provider tests: adapters, secrets, defaults, platform gate and legacy."""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.v2.ai.api import get_ai_secret_store, get_ai_transport
from app.v2.ai.secrets import InMemorySecretStore
from app.v2.ai.transport import HttpResponse, TransportConnectionError, TransportTimeout
from app.v2.db import configure_sqlite, create_v2_db, get_v2_session

OPENAI_BASE = "http://127.0.0.1:8080/v1"
OLLAMA_BASE = "http://127.0.0.1:11434"


class FakeTransport:
    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[dict] = []

    def route(self, url: str, payload: object = None, status: int = 200) -> None:
        self.routes[url] = (status, payload)

    def request(self, method, url, *, headers, json_body, timeout, max_bytes):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json_body})
        route = self.routes.get(url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return HttpResponse(status=404, headers={}, body=json.dumps({"error": "not found"}).encode())
        status, payload = route
        return HttpResponse(status=status, headers={}, body=json.dumps(payload, ensure_ascii=False).encode())


def make_payload(kind: str = "openai", **overrides):
    payload = {
        "kind": kind,
        "label": "测试 Provider" if kind == "openai" else "本地 Ollama",
        "base_url": OPENAI_BASE if kind == "openai" else OLLAMA_BASE,
        "model": "gpt-test" if kind == "openai" else "llama-test",
        "params": {"temperature": 0.2, "max_tokens": 64, "timeout_seconds": 5},
    }
    payload.update(overrides)
    return payload


def create_provider(client: TestClient, kind: str = "openai", **overrides):
    response = client.post("/api/v2/ai/providers", json=make_payload(kind, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def ai_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    configure_sqlite(engine)
    create_v2_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = InMemorySecretStore()
    transport = FakeTransport()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override_session
    app.dependency_overrides[get_ai_secret_store] = lambda: store
    app.dependency_overrides[get_ai_transport] = lambda: transport
    try:
        with TestClient(app) as client:
            yield client, store, transport
    finally:
        app.dependency_overrides.pop(get_v2_session, None)
        app.dependency_overrides.pop(get_ai_secret_store, None)
        app.dependency_overrides.pop(get_ai_transport, None)
        engine.dispose()


def _ollama_tags(transport: FakeTransport, names: list[str]) -> None:
    transport.route(
        f"{OLLAMA_BASE}/api/tags",
        {"models": [{"name": name, "size": 123, "modified_at": "2026-01-01T00:00:00Z"} for name in names]},
    )


def _openai_chat(transport: FakeTransport, text: str = "你好") -> None:
    transport.route(
        f"{OPENAI_BASE}/chat/completions",
        {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )


def test_ollama_connection_and_models(ai_client):
    client, _store, transport = ai_client
    _ollama_tags(transport, ["llama-test"])
    provider = create_provider(client, "ollama")
    response = client.post(f"/api/v2/ai/providers/{provider['id']}/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["model_count"] == 1 and body["model"] == "llama-test"
    models = client.get(f"/api/v2/ai/providers/{provider['id']}/models")
    assert models.status_code == 200 and models.json()["models"][0]["id"] == "llama-test"


def test_ollama_unavailable(ai_client):
    client, _store, transport = ai_client
    transport.routes[f"{OLLAMA_BASE}/api/tags"] = TransportConnectionError("connection refused")
    provider = create_provider(client, "ollama")
    response = client.post(f"/api/v2/ai/providers/{provider['id']}/test")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "provider_unavailable" and "Ollama" in error["message"]


def test_openai_compatible_chat_and_usage(ai_client):
    client, _store, transport = ai_client
    _openai_chat(transport, "这是回答")
    provider = create_provider(client, api_key="sk-test-123456")
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"],
        "messages": [{"role": "user", "content": "你好"}],
        "system_prompt": "简洁回答",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"]["content"] == "这是回答"
    assert body["usage"]["total_tokens"] == 5
    sent = transport.calls[-1]["json"]
    assert sent["messages"][0] == {"role": "system", "content": "简洁回答"}
    assert sent["stream"] is False and sent["model"] == "gpt-test"


def test_missing_api_key_is_rejected(ai_client):
    client, _store, _transport = ai_client
    provider = create_provider(client)
    assert provider["has_key"] is False
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_api_key"


def test_api_key_never_returned_by_query_api(ai_client):
    client, _store, _transport = ai_client
    secret = "sk-live-SUPERSECRET-98765"
    provider = create_provider(client, api_key=secret)
    listed = client.get("/api/v2/ai/providers")
    assert listed.status_code == 200
    assert secret not in listed.text
    assert provider["has_key"] is True
    assert "api_key" not in listed.text and "key_ref" not in listed.text


def test_update_and_clear_api_key(ai_client):
    client, _store, transport = ai_client
    _openai_chat(transport)
    provider = create_provider(client, api_key="sk-old-key")
    rotated = client.patch(f"/api/v2/ai/providers/{provider['id']}", json={"api_key": "sk-new-key"})
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["has_key"] is True
    chat = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert chat.status_code == 200
    assert transport.calls[-1]["headers"].get("Authorization") == "Bearer sk-new-key"

    cleared = client.patch(f"/api/v2/ai/providers/{provider['id']}", json={"clear_api_key": True})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["has_key"] is False
    missing = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "missing_api_key"


def test_auth_failure_is_unified(ai_client):
    client, _store, transport = ai_client
    transport.route(f"{OPENAI_BASE}/chat/completions", {"error": "invalid key"}, status=401)
    provider = create_provider(client, api_key="sk-bad-key")
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_failed"


def test_request_timeout_is_unified(ai_client):
    client, _store, transport = ai_client
    transport.routes[f"{OPENAI_BASE}/chat/completions"] = TransportTimeout("slow")
    provider = create_provider(client, api_key="sk-test-timeout")
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "timeout" and error["retryable"] is True


def test_invalid_base_url_is_rejected(ai_client):
    client, _store, _transport = ai_client
    response = client.post("/api/v2/ai/providers", json=make_payload(base_url="http://169.254.169.254/latest"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_base_url"


def test_ollama_model_not_found(ai_client):
    client, _store, transport = ai_client
    _ollama_tags(transport, ["other-model"])
    provider = create_provider(client, "ollama")
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


def test_multi_provider_keys_are_isolated(ai_client):
    client, _store, transport = ai_client
    _openai_chat(transport)
    first = create_provider(client, label="A", api_key="sk-key-A")
    second = create_provider(client, label="B", api_key="sk-key-B", is_default=False)
    patched = client.patch(f"/api/v2/ai/providers/{first['id']}", json={"label": "A2"})
    assert patched.status_code == 200 and patched.json()["label"] == "A2"
    listed = client.get("/api/v2/ai/providers").json()
    by_id = {item["id"]: item for item in listed}
    assert by_id[second["id"]]["label"] == "B" and by_id[second["id"]]["model"] == "gpt-test"
    for provider in (first, second):
        response = client.post("/api/v2/ai/chat", json={
            "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
        })
        assert response.status_code == 200
    auth_headers = [call["headers"].get("Authorization") for call in transport.calls if call["url"].endswith("/chat/completions")]
    assert auth_headers[-2:] == ["Bearer sk-key-A", "Bearer sk-key-B"]


def test_default_model_after_provider_deletion(ai_client):
    client, _store, _transport = ai_client
    first = create_provider(client, label="A", model="gpt-a", is_default=True, api_key="sk-a")
    second = create_provider(client, label="B", model="gpt-b", api_key="sk-b")
    before = {item["id"]: item for item in client.get("/api/v2/ai/providers").json()}
    assert before[first["id"]]["is_default"] is True
    deleted = client.delete(f"/api/v2/ai/providers/{first['id']}")
    assert deleted.status_code == 204
    after = {item["id"]: item for item in client.get("/api/v2/ai/providers").json()}
    remaining = after[second["id"]]
    assert remaining["is_default"] is True
    settings = client.get("/api/v2/settings").json()
    assert settings["default_model"] == "gpt-b"


def test_mobile_cannot_use_ollama(ai_client):
    client, _store, transport = ai_client
    mobile_headers = {"X-Hephaestus-Platform": "mobile"}
    forbidden = client.post("/api/v2/ai/providers", json=make_payload("ollama"), headers=mobile_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "mobile_ollama_forbidden"
    _ollama_tags(transport, ["llama-test"])
    provider = create_provider(client, "ollama")
    chat = client.post("/api/v2/ai/chat", headers=mobile_headers, json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert chat.status_code == 403
    assert chat.json()["error"]["code"] == "mobile_ollama_forbidden"


def test_logs_and_errors_do_not_contain_api_keys(ai_client, caplog):
    client, _store, transport = ai_client
    caplog.set_level(logging.INFO, logger="hephaestus.ai")
    secret = "sk-log-SECRET-abcdef"
    _openai_chat(transport)
    provider = create_provider(client, api_key=secret)
    response = client.post("/api/v2/ai/chat", json={
        "provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}],
    })
    assert response.status_code == 200
    assert secret not in response.text
    assert secret not in caplog.text
    assert "sk-" not in caplog.text


def test_legacy_state_api_still_works(ai_client):
    client, _store, _transport = ai_client
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/v2/meta").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v2/ai/chat" in paths and "/api/state" in paths


def test_provider_config_survives_restart(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai.db'}", connect_args={"check_same_thread": False})
    configure_sqlite(engine)
    create_v2_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = InMemorySecretStore()
    transport = FakeTransport()
    _openai_chat(transport)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override_session
    app.dependency_overrides[get_ai_secret_store] = lambda: store
    app.dependency_overrides[get_ai_transport] = lambda: transport
    try:
        with TestClient(app) as first:
            created = create_provider(first, api_key="sk-persist-123")
        with TestClient(app) as second:
            listed = second.get("/api/v2/ai/providers")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == created["id"]
            assert listed.json()[0]["has_key"] is True
            chat = second.post("/api/v2/ai/chat", json={
                "provider_id": created["id"], "messages": [{"role": "user", "content": "after restart"}],
            })
            assert chat.status_code == 200
    finally:
        app.dependency_overrides.pop(get_v2_session, None)
        app.dependency_overrides.pop(get_ai_secret_store, None)
        app.dependency_overrides.pop(get_ai_transport, None)
        engine.dispose()
