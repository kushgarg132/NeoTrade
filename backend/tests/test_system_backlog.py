"""The admin's backlog of future enhancements (/system/backlog)."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db as database
from backend.system import router as system_router


def _user(role):
    return User(id="alice", google_sub="g", email="a@x.io", name="A", role=role,
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def mongo(monkeypatch):
    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    return mongo


def _client(role="admin"):
    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


URL = "/api/v1/system/backlog"


def test_create_list_patch_delete(mongo):
    client = _client()
    first = client.post(URL, json={"title": "Free beta", "area": "Product"}).json()
    second = client.post(URL, json={"title": "Billing", "area": "Product", "status": "next", "effort": "L"}).json()
    third = client.post(URL, json={"title": "Domain", "area": "Ops"}).json()
    assert first["status"] == "idea" and first["id"] and second["rank"] == 0 and third["rank"] == 1
    client.delete(f"{URL}/{third['id']}")

    items = client.get(URL).json()["items"]
    assert [i["title"] for i in items] == ["Billing", "Free beta"]  # next before idea

    patched = client.patch(f"{URL}/{first['id']}", json={"why": "find weekly users", "rank": 5}).json()
    assert patched["why"] == "find weekly users" and patched["rank"] == 5 and patched["title"] == "Free beta"

    assert client.delete(f"{URL}/{first['id']}").json() == {"ok": True}
    assert [i["title"] for i in client.get(URL).json()["items"]] == ["Billing"]


@pytest.mark.parametrize("body", [
    {"title": "", "area": "UI"},
    {"title": "x" * 141, "area": "UI"},
    {"title": "ok", "area": "Foo"},
    {"title": "ok", "area": "UI", "status": "later"},
])
def test_validation_422(mongo, body):
    assert _client().post(URL, json=body).status_code == 422


def test_done_at_stamped_and_cleared(mongo):
    client = _client()
    item = client.post(URL, json={"title": "Ship it", "area": "Ops"}).json()
    done = client.patch(f"{URL}/{item['id']}", json={"status": "done"}).json()
    assert done["done_at"]
    reopened = client.patch(f"{URL}/{item['id']}", json={"status": "next"}).json()
    assert reopened["done_at"] is None


def test_patch_unknown_or_bad_id_is_404(mongo):
    client = _client()
    assert client.patch(f"{URL}/0123456789abcdef01234567", json={"why": "x"}).status_code == 404
    assert client.patch(f"{URL}/nope", json={"why": "x"}).status_code == 404
    assert client.delete(f"{URL}/nope").status_code == 404


def test_backlog_is_admin_only(mongo):
    client = _client(role="user")
    assert client.get(URL).status_code == 403
    assert client.post(URL, json={"title": "x", "area": "UI"}).status_code == 403
    assert client.patch(f"{URL}/0123456789abcdef01234567", json={"why": "x"}).status_code == 403
    assert client.delete(f"{URL}/0123456789abcdef01234567").status_code == 403


def test_seed_is_idempotent(mongo):
    import asyncio

    from backend.system.seed_backlog import SEED, seed

    assert asyncio.run(seed(mongo)) == len(SEED)
    assert asyncio.run(seed(mongo)) == 0
    docs = asyncio.run(mongo["backlog"].find().to_list(length=None))
    assert len(docs) == len(SEED) and all(d["source"] for d in docs)
    assert len({d["title"] for d in SEED}) == len(SEED)
