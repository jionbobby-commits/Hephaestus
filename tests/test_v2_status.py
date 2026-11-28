from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.v2.db import configure_sqlite, create_v2_db, get_v2_session


@contextmanager
def _client(engine):
    configure_sqlite(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_v2_session, None)


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed_legacy(engine, notes=2, tags=1):
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE frontend_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        ))
        payload = {
            "notes": [{"id": f"n{i}", "title": f"笔记{i}", "html": "", "tags": []} for i in range(notes)],
            "tags": [{"id": f"t{i}", "name": f"标签{i}", "color": "#7c83e6"} for i in range(tags)],
            "ui": {"theme": "dark"},
        }
        connection.execute(
            text("INSERT INTO frontend_state (id, payload) VALUES (1, :payload)"),
            {"payload": json.dumps(payload, ensure_ascii=False)},
        )


def _mark_ready(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO v2_schema_migrations (version, applied_at, checksum) VALUES (1, '2026-11-23T00:00:00.000Z', :checksum)"
        ), {"checksum": "a" * 64})
        connection.execute(text(
            "INSERT INTO v2_import_meta (key, value) VALUES ('frontend_state_migrated_at', '2026-11-23T00:00:00.000Z')"
        ))


def test_status_legacy_is_read_only_and_reports_counts():
    engine = _memory_engine()
    _seed_legacy(engine, notes=3, tags=2)
    try:
        with _client(engine) as client:
            response = client.get("/api/v2/status")
            assert response.status_code == 200
            body = response.json()
            assert body["data_mode"] == "legacy"
            assert body["fallback"] is True
            assert body["legacy"]["initialized"] is True
            assert body["legacy"]["note_count"] == 3
            assert body["legacy"]["tag_count"] == 2
            assert body["v2"]["available"] is False
        assert "v2_notes" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_status_pending_when_v2_schema_has_no_marker():
    engine = _memory_engine()
    create_v2_db(engine)
    try:
        with _client(engine) as client:
            body = client.get("/api/v2/status").json()
        assert body["data_mode"] == "migration_pending"
        assert body["v2"]["schema_ready"] is True
        assert body["v2"]["migration_version"] is None
        assert body["fallback"] is True
    finally:
        engine.dispose()


def test_status_ready_with_marker_and_counts():
    engine = _memory_engine()
    create_v2_db(engine)
    _mark_ready(engine)
    try:
        with _client(engine) as client:
            body = client.get("/api/v2/status").json()
        assert body["data_mode"] == "v2_ready"
        assert body["fallback"] is False
        assert body["v2"]["schema_ready"] is True
        assert body["v2"]["migration_version"] == 1
        assert body["v2"]["note_count"] == 0
    finally:
        engine.dispose()


def test_explicit_failure_falls_back_and_never_promotes():
    engine = _memory_engine()
    create_v2_db(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO v2_import_meta (key, value) VALUES ('migration_status', 'failed')"
        ))
    try:
        with _client(engine) as client:
            body = client.get("/api/v2/status").json()
        assert body["data_mode"] == "migration_failed"
        assert body["fallback"] is True
        assert body["v2"]["explicit_status"] == "failed"
    finally:
        engine.dispose()


def test_malformed_legacy_payload_is_diagnosed_not_fatal():
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE frontend_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        ))
        connection.execute(text("INSERT INTO frontend_state (id, payload) VALUES (1, '{bad json')"))
    try:
        with _client(engine) as client:
            response = client.get("/api/v2/status")
            assert response.status_code == 200
            body = response.json()
        assert body["data_mode"] == "legacy"
        assert body["legacy"]["initialized"] is False
        assert body["legacy"]["error"]
    finally:
        engine.dispose()
