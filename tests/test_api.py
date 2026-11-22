import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def create_sample(client, title="Python 学习", content="FastAPI 入门", category="学习"):
    response = client.post("/notes", json={"title": title, "content": content, "category": category})
    assert response.status_code == 201
    return response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_note(client):
    note = create_sample(client)
    response = client.get(f"/notes/{note['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "Python 学习"


def test_list_pagination_and_keyword_search(client):
    create_sample(client, "Python 学习")
    create_sample(client, "Java 学习", "Spring Boot", "开发")
    response = client.get("/notes?page=1&page_size=1&keyword=Python")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1


def test_legacy_q_search_parameter_is_compatible(client):
    create_sample(client)
    response = client.get("/notes?q=FastAPI")
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_category_filter(client):
    create_sample(client, category="学习")
    create_sample(client, "Java", "Spring", "开发")
    response = client.get("/notes?category=开发")
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["category"] == "开发"


def test_patch_updates_only_supplied_fields(client):
    note = create_sample(client, content="原内容")
    response = client.patch(f"/notes/{note['id']}", json={"title": "新标题"})
    assert response.status_code == 200
    assert response.json()["title"] == "新标题"
    assert response.json()["content"] == "原内容"


def test_put_compatibility_for_existing_frontend(client):
    note = create_sample(client)
    response = client.put(f"/notes/{note['id']}", json={
        "title": "更新标题", "content": "更新内容", "category": "开发", "is_favorite": True
    })
    assert response.status_code == 200
    assert response.json()["is_favorite"] is True


def test_favorite_endpoints(client):
    first = create_sample(client)
    second = create_sample(client, "另一条笔记")
    marked = client.patch(f"/notes/{first['id']}/favorite", json={"is_favorite": True})
    assert marked.status_code == 200
    response = client.get("/notes/favorites")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == first["id"]
    assert client.get(f"/notes/{second['id']}").json()["is_favorite"] is False


def test_delete_returns_204_and_missing_note_returns_404(client):
    note = create_sample(client)
    deleted = client.delete(f"/notes/{note['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/notes/{note['id']}").status_code == 404


def test_rejects_blank_title_and_empty_patch(client):
    invalid = client.post("/notes", json={"title": "   "})
    assert invalid.status_code == 422
    note = create_sample(client)
    empty_patch = client.patch(f"/notes/{note['id']}", json={})
    assert empty_patch.status_code == 422


def test_frontend_state_is_saved_and_loaded(client):
    state = {
        "notes": [{"id": "n1", "title": "测试笔记", "html": "<p>内容</p>", "tags": []}],
        "tags": [{"id": "t1", "name": "学习", "color": "#00aa00"}],
        "ui": {"theme": "dark", "layout": "grid"},
    }
    saved = client.put("/api/state", json=state)
    assert saved.status_code == 200
    loaded = client.get("/api/state")
    assert loaded.status_code == 200
    assert loaded.json() == {"initialized": True, "state": state}


def test_rejects_invalid_frontend_state(client):
    response = client.put("/api/state", json={"notes": "not-a-list", "tags": []})
    assert response.status_code == 422


def test_page_size_limit(client):
    response = client.get("/notes?page_size=101")
    assert response.status_code == 422


def test_patch_rejects_null_values(client):
    note = create_sample(client)
    response = client.patch(f"/notes/{note['id']}", json={"title": None})
    assert response.status_code == 422
