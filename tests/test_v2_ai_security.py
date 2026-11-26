"""C1.1 security regression tests: SSRF, DNS pinning, Host/Origin, secrets, caps."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.v2.ai import service as service_module
from app.v2.ai.api import get_ai_secret_store, get_ai_transport
from app.v2.ai.errors import AIError
from app.v2.ai.secrets import FileSecretStore, InMemorySecretStore, SecretStoreError
from app.v2.ai.security import redact_secret, resolve_base_url, validate_base_url
from app.v2.ai.service import AIProviderService
from app.v2.ai.transport import (
    HttpResponse,
    PinnedHttpTransport,
    ResponseTooLarge,
    TransportConnectionError,
    TransportTimeout,
)
from app.v2.db import configure_sqlite, create_v2_db, get_v2_session

OPENAI_BASE = "http://127.0.0.1:8080/v1"


class FakeTransport:
    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[dict] = []

    def route(self, url: str, payload: object = None, status: int = 200) -> None:
        self.routes[url] = (status, payload)

    def request(self, method, url, *, headers, json_body, timeout, max_bytes, resolved_ips=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json_body,
                "resolved_ips": resolved_ips,
            }
        )
        route = self.routes.get(url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return HttpResponse(status=404, headers={}, body=b'{"error":"not found"}')
        status, payload = route
        return HttpResponse(
            status=status,
            headers={},
            body=json.dumps(payload, ensure_ascii=False).encode(),
        )


def _payload(**overrides):
    payload = {
        "kind": "openai",
        "label": "安全测试 Provider",
        "base_url": OPENAI_BASE,
        "model": "gpt-test",
        "params": {"temperature": 0.2, "max_tokens": 64, "timeout_seconds": 5},
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def ai_client(monkeypatch):
    monkeypatch.delenv("HEPHAESTUS_AI_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("HEPHAESTUS_AI_ALLOWED_HOSTS", raising=False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def _create(client: TestClient, **overrides) -> dict:
    response = client.post("/api/v2/ai/providers", json=_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ---------- Host / Origin / body boundary ----------


def test_host_header_rebinding_is_rejected(ai_client):
    client, _store, _transport = ai_client
    response = client.get("/api/v2/ai/providers", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_host"


def test_x_forwarded_host_does_not_override_host(ai_client):
    client, _store, _transport = ai_client
    response = client.get(
        "/api/v2/ai/providers",
        headers={"Host": "evil.example", "X-Forwarded-Host": "localhost"},
    )
    assert response.status_code == 403


def test_cross_origin_and_null_origin_are_rejected(ai_client):
    client, _store, _transport = ai_client
    for origin in ("http://evil.example", "null"):
        response = client.get("/api/v2/ai/providers", headers={"Origin": origin})
        assert response.status_code == 403, origin
        assert response.json()["error"]["code"] == "invalid_origin"


def test_same_origin_and_referer_are_allowed(ai_client):
    client, _store, _transport = ai_client
    assert (
        client.get("/api/v2/ai/providers", headers={"Origin": "http://testserver"}).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v2/ai/providers", headers={"Referer": "http://testserver/index.html"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v2/ai/providers", headers={"Referer": "http://evil.example/index.html"}
        ).status_code
        == 403
    )


def test_allowed_hosts_env_matches_optional_port(ai_client, monkeypatch):
    client, _store, _transport = ai_client
    monkeypatch.setenv("HEPHAESTUS_AI_ALLOWED_HOSTS", "app.local:8000")
    assert (
        client.get("/api/v2/ai/providers", headers={"Host": "app.local:8000"}).status_code
        == 200
    )
    assert (
        client.get("/api/v2/ai/providers", headers={"Host": "app.local"}).status_code
        == 403
    )


def test_body_limit_and_content_encoding(ai_client):
    client, _store, _transport = ai_client
    response = client.post(
        "/api/v2/ai/chat", content=b"x" * 2_000_001, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "body_too_large"

    response = client.post(
        "/api/v2/ai/chat",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_encoding"


def test_ai_responses_disable_caching_and_sniffing(ai_client):
    client, _store, _transport = ai_client
    response = client.get("/api/v2/ai/providers")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


# ---------- SSRF and DNS pinning ----------


def test_cgnat_and_ipv4_mapped_metadata_are_rejected():
    with pytest.raises(AIError) as exc:
        validate_base_url("openai", "https://100.64.0.1:8443/v1")
    assert exc.value.code == "invalid_base_url"

    with pytest.raises(AIError) as exc:
        validate_base_url("openai", "https://[::ffff:169.254.169.254]/v1")
    assert exc.value.code == "invalid_base_url"


def test_resolve_base_url_returns_exact_pinned_addresses():
    url, addresses = resolve_base_url(
        "openai",
        "https://api.example.test/v1",
        resolver=lambda host, port: ["1.1.1.1", "1.1.1.1", "8.8.8.8"],
    )
    assert url == "https://api.example.test/v1"
    assert addresses == ["1.1.1.1", "8.8.8.8"]


def test_resolver_private_answer_is_rejected():
    with pytest.raises(AIError) as exc:
        resolve_base_url(
            "openai",
            "https://api.example.test/v1",
            resolver=lambda host, port: ["100.64.0.1"],
        )
    assert exc.value.code == "invalid_base_url"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.server.seen.append((self.path, self.headers.get("Host")))  # type: ignore[attr-defined]
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(0.4)
        if self.path == "/large":
            body = b"x" * 5000
        else:
            body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_http():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://pinned.example:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_transport_connects_to_pinned_ip_and_keeps_original_host(local_http):
    base, server = local_http
    transport = PinnedHttpTransport()
    response = transport.request(
        "GET",
        base + "/hello",
        headers={"Host": "evil.example"},
        json_body=None,
        timeout=2,
        max_bytes=1024,
        resolved_ips=["127.0.0.1"],
    )
    assert response.status == 200
    assert server.seen[-1][1] == f"pinned.example:{server.server_port}"
    assert server.seen[-1][0] == "/hello"


def test_transport_does_not_follow_redirects(local_http):
    base, _server = local_http
    response = PinnedHttpTransport().request(
        "GET",
        base + "/redirect",
        headers={},
        json_body=None,
        timeout=2,
        max_bytes=1024,
        resolved_ips=["127.0.0.1"],
    )
    assert response.status == 302


def test_transport_response_cap(local_http):
    base, _server = local_http
    with pytest.raises(ResponseTooLarge):
        PinnedHttpTransport().request(
            "GET",
            base + "/large",
            headers={},
            json_body=None,
            timeout=2,
            max_bytes=100,
            resolved_ips=["127.0.0.1"],
        )


def test_transport_timeout(local_http):
    base, _server = local_http
    with pytest.raises(TransportTimeout):
        PinnedHttpTransport().request(
            "GET",
            base + "/slow",
            headers={},
            json_body=None,
            timeout=0.1,
            max_bytes=1024,
            resolved_ips=["127.0.0.1"],
        )


def test_transport_rejects_empty_validated_addresses(local_http):
    base, _server = local_http
    with pytest.raises(TransportConnectionError):
        PinnedHttpTransport().request(
            "GET",
            base + "/hello",
            headers={},
            json_body=None,
            timeout=2,
            max_bytes=1024,
            resolved_ips=[],
        )


# ---------- redaction and key handling ----------


def test_secret_redaction_covers_common_shapes():
    cases = [
        "Authorization: Bearer sk-abcdefgh12345678",
        "x-api-key: sk-abcdefgh12345678",
        '{"api_key": "sk-abcdefgh12345678"}',
        "https://example.test/?api_key=sk-abcdefgh12345678",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "the key is sk-abcdefgh12345678",
    ]
    for text in cases:
        redacted = redact_secret(text)
        assert "sk-abcdefgh12345678" not in redacted
        assert "dXNlcjpwYXNzd29yZA" not in redacted
        assert "[REDACTED]" in redacted


def test_api_key_never_returned_and_echoed_key_is_redacted(ai_client):
    client, _store, transport = ai_client
    secret = "sk-echo-secret-12345678"
    provider = _create(client, api_key=secret)
    assert provider["has_key"] is True
    listing = client.get("/api/v2/ai/providers")
    assert secret not in listing.text
    assert "key_ref" not in listing.text

    transport.route(
        OPENAI_BASE + "/chat/completions",
        {"error": f"bad key {secret}"},
        status=401,
    )
    response = client.post(
        "/api/v2/ai/chat",
        json={"provider_id": provider["id"], "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401
    assert secret not in response.text
    assert "[REDACTED]" in response.json()["error"]["details"]["response"]


def test_validation_errors_do_not_echo_api_key(ai_client):
    client, _store, _transport = ai_client
    provider = _create(client)
    secret = "sk-validation-secret-12345678"

    response = client.patch(
        f"/api/v2/ai/providers/{provider['id']}",
        json={"api_key": secret, "clear_api_key": True},
    )

    assert response.status_code == 422
    assert secret not in response.text
    encoded = json.dumps(response.json(), ensure_ascii=False)
    assert "[REDACTED]" in encoded
    assert "api_key" in encoded


def test_client_supplied_key_ref_cannot_bind_arbitrary_secret(ai_client):
    client, store, _transport = ai_client
    store.set("provider-stolen", "sk-stolen-secret-12345678")
    provider = _create(client, key_ref="provider-stolen")
    assert provider["has_key"] is False

    response = client.post(f"/api/v2/ai/providers/{provider['id']}/test")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_api_key"


# ---------- secret file ----------


def test_secret_file_is_ciphertext_and_restricted(tmp_path):
    path = tmp_path / "secrets.json"
    store = FileSecretStore(path)
    store.set("provider-a", "sk-plain-secret-12345678")
    raw = path.read_text(encoding="utf-8")
    assert "sk-plain-secret-12345678" not in raw
    assert store.get("provider-a") == "sk-plain-secret-12345678"
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode) & 0o777
        assert mode == 0o600


def test_secret_store_separate_instances_do_not_lose_keys(tmp_path):
    path = tmp_path / "secrets.json"
    stores = [FileSecretStore(path) for _ in range(4)]

    def write(index: int):
        stores[index % len(stores)].set(f"provider-{index}", f"secret-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    for index in range(24):
        assert FileSecretStore(path).get(f"provider-{index}") == f"secret-{index}"


def test_secret_store_separate_processes_do_not_lose_keys(tmp_path):
    path = tmp_path / "secrets.json"
    script = (
        "import sys; from pathlib import Path; "
        "from app.v2.ai.secrets import FileSecretStore; "
        "FileSecretStore(Path(sys.argv[1])).set(sys.argv[2], sys.argv[3])"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), f"process-{index}", f"value-{index}"],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(3)
    ]
    for process in processes:
        _out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err.decode(errors="replace")

    store = FileSecretStore(path)
    for index in range(3):
        assert store.get(f"process-{index}") == f"value-{index}"


def test_atomic_replace_failure_keeps_previous_secret(tmp_path, monkeypatch):
    path = tmp_path / "secrets.json"
    store = FileSecretStore(path)
    store.set("provider-a", "old-secret")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SecretStoreError):
        store.set("provider-b", "new-secret")
    monkeypatch.undo()
    assert store.get("provider-a") == "old-secret"
    assert store.get("provider-b") is None


def test_ai_call_slot_limit(monkeypatch):
    slot = threading.BoundedSemaphore(1)
    monkeypatch.setattr(service_module, "_CALL_SLOTS", slot)
    slot.acquire()
    try:
        with pytest.raises(AIError) as exc:
            AIProviderService._call(lambda: None)
        assert exc.value.code == "too_many_requests"
        assert exc.value.status_code == 429
    finally:
        slot.release()
