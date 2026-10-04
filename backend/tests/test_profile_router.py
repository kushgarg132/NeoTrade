from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.profile.store import ProfileStore
from backend.routers import profile as profile_router


def _user(user_id):
    return User(id=user_id, google_sub=f"sub-{user_id}", email=f"{user_id}@example.com", name=user_id.title(),
                picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


def _client(db, user_id="alice"):
    app = FastAPI()
    app.include_router(profile_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(user_id)
    app.dependency_overrides[profile_router.get_profile_store] = lambda: ProfileStore(db)
    return TestClient(app)


def test_get_returns_google_account_and_empty_profile():
    body = _client(AsyncMongoMockClient()["test_db"]).get("/api/v1/profile").json()
    assert body["account"]["name"] == "Alice" and body["account"]["email"] == "alice@example.com"
    assert body["account"]["picture"] is None
    assert body["profile"] == {"memories": []}


def test_put_validates_and_saves():
    client = _client(AsyncMongoMockClient()["test_db"])
    assert client.put("/api/v1/profile", json={"goals": "x" * 501}).status_code == 422
    resp = client.put("/api/v1/profile", json={"display_name": "Kush", "styles": ["swing", "swing"]})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Kush" and resp.json()["styles"] == ["swing"]


def test_memories_endpoints():
    client = _client(AsyncMongoMockClient()["test_db"])
    resp = client.post("/api/v1/profile/memories", json={"text": "Saving for a house"})
    assert resp.status_code == 201 and resp.json()["source"] == "manual"
    assert client.post("/api/v1/profile/memories", json={"text": "saving for a house"}).status_code == 409
    memory_id = resp.json()["id"]
    assert client.delete(f"/api/v1/profile/memories/{memory_id}").status_code == 204
    assert client.delete(f"/api/v1/profile/memories/{memory_id}").status_code == 404


def test_cannot_delete_another_users_memory():
    db = AsyncMongoMockClient()["test_db"]
    memory_id = _client(db, "alice").post("/api/v1/profile/memories", json={"text": "Saving for a house"}).json()["id"]
    assert _client(db, "bob").delete(f"/api/v1/profile/memories/{memory_id}").status_code == 404
    assert len(_client(db, "alice").get("/api/v1/profile").json()["profile"]["memories"]) == 1
