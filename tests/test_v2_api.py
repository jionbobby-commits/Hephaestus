from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.v2.db import configure_sqlite, create_v2_db, get_v2_session


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    configure_sqlite(engine)
    create_v2_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_v2_session, None)
    engine.dispose()


def test_v2_note_lifecycle_over_http(client: TestClient):
    tag = client.post("/api/v2/tags", json={"name": "工作", "color": "#7c83e6"})
    assert tag.status_code == 201
    tag_id = tag.json()["id"]

    created = client.post("/api/v2/notes", json={
        "title": "API 笔记", "content_html": "<p>内容</p>", "tags": [tag_id],
    })
    assert created.status_code == 201
    note = created.json()
    note_id = note["id"]
    assert note["revision"] == 1 and note["tags"][0]["name"] == "工作"

    listed = client.get("/api/v2/notes", params={"q": "内容"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = client.patch(f"/api/v2/notes/{note_id}", json={"title": "改过", "revision": 1})
    assert patched.status_code == 200 and patched.json()["revision"] == 2
    conflict = client.patch(f"/api/v2/notes/{note_id}", json={"title": "冲突", "revision": 1})
    assert conflict.status_code == 409

    favorite = client.patch(f"/api/v2/notes/{note_id}/favorite", json={"favorite": True})
    assert favorite.status_code == 200 and favorite.json()["is_favorite"] is True
    assert client.get("/api/v2/notes", params={"favorite": "true"}).json()["total"] == 1

    trash = client.delete(f"/api/v2/notes/{note_id}")
    assert trash.status_code == 204
    assert client.get("/api/v2/notes").json()["total"] == 0
    assert client.get("/api/v2/notes", params={"trashed": "true"}).json()["total"] == 1
    restored = client.post(f"/api/v2/notes/{note_id}/restore")
    assert restored.status_code == 200 and restored.json()["is_trashed"] is False

    delete = client.delete(f"/api/v2/notes/{note_id}", params={"permanent": "true"})
    assert delete.status_code == 204
    assert client.get(f"/api/v2/notes/{note_id}").status_code == 404


def test_v2_settings_and_meta(client: TestClient):
    meta = client.get("/api/v2/meta")
    assert meta.status_code == 200 and meta.json()["contract_version"] == "2.0"
    settings = client.patch("/api/v2/settings", json={"theme": "dark", "locale": "en"})
    assert settings.status_code == 200
    assert settings.json()["theme"] == "dark" and settings.json()["locale"] == "en"


def test_v2_missing_schema_is_503_not_500():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_v2_session] = override
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/v2/notes")
        assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_v2_session, None)
        engine.dispose()
