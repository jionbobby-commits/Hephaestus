import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_note_crud_and_pagination(client):
    created = client.post(
        "/notes",
        json={"title": "Python 学习", "content": "FastAPI", "category": "学习"},
    )
    assert created.status_code == 201
    note_id = created.json()["id"]

    listed = client.get("/notes?page=1&page_size=5&q=Python")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == note_id

    updated = client.put(
        f"/notes/{note_id}",
        json={"title": "Python 进阶", "content": "SQLAlchemy", "category": "开发", "is_favorite": True},
    )
    assert updated.status_code == 200
    assert updated.json()["is_favorite"] is True

    assert client.get(f"/notes/{note_id}").status_code == 200
    assert client.delete(f"/notes/{note_id}").status_code == 204
    assert client.get(f"/notes/{note_id}").status_code == 404


def test_rejects_blank_title(client):
    response = client.post("/notes", json={"title": "   "})
    assert response.status_code == 422


def test_frontend_state_is_saved_and_loaded(client):
    state = {
        "notes": [{"id": "n1", "title": "测试笔记", "html": "<p>内容</p>", "tags": []}],
        "tags": [{"id": "t1", "name": "学习", "color": "#00aa00"}],
        "ui": {"theme": "dark", "layout": "grid"},
    }
    saved = client.put("/api/state", json=state)
    assert saved.status_code == 200
    assert saved.json() == {"saved": True, "note_count": 1}

    loaded = client.get("/api/state")
    assert loaded.status_code == 200
    assert loaded.json() == {"initialized": True, "state": state}


def test_rejects_invalid_frontend_state(client):
    response = client.put("/api/state", json={"notes": "not-a-list", "tags": []})
    assert response.status_code == 422
