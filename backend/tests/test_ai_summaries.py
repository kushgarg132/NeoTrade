"""The stored-AI-text endpoints: market brief, latest portfolio review, cached analyst note.
None of them may call a model; each needs a signed-in user; the review is the caller's own."""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend import database
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import market_data
from backend.routers import mine as mine_router

NOW = datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)  # 16:30 IST


class Redis:
    def __init__(self, data=None, ttl=None):
        self.data, self._ttl = data or {}, ttl

    async def get(self, key):
        return self.data.get(key)

    async def ttl(self, key):
        return self._ttl


def _user(uid="alice"):
    return User(id=uid, google_sub="g", email="a@x.io", name="A", created_at=NOW)


@pytest.fixture
def app(monkeypatch):
    mongo = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(mine_router.db, "db", mongo)
    monkeypatch.setattr(database.db, "redis", Redis())
    app = FastAPI()
    for router in (market_data.router, mine_router.router):  # mounted behind auth, as in server.py
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
    app.state.mongo = mongo
    return app


@pytest.fixture
def client(app):
    app.dependency_overrides[get_current_user] = lambda: _user()
    return TestClient(app)


@pytest.mark.parametrize("path", ["/market/brief", "/mine/review/latest", "/research/TCS/note"])
def test_auth_required(app, path):
    assert TestClient(app).get(f"/api/v1{path}").status_code in (401, 403)


def test_brief_shape_and_empty(client):
    assert client.get("/api/v1/market/brief").status_code == 404
    database.db.redis.data["market:brief"] = json.dumps({"text": "Markets firm.", "at": NOW.timestamp(), "regime": "risk_on", "items": []})
    assert client.get("/api/v1/market/brief").json() == {"text": "Markets firm.", "as_of": NOW.isoformat(), "regime": "risk_on"}


def test_review_is_latest_with_text_and_scoped_to_user(client, app):
    snaps = [
        {"user_id": "alice", "at": datetime(2026, 10, 16, 10, 30), "summary": "Older review."},
        {"user_id": "alice", "at": datetime(2026, 10, 19, 10, 30), "summary": "Latest review."},
        {"user_id": "alice", "at": datetime(2026, 10, 19, 10, 45), "summary": None},  # a run with no write-up
        {"user_id": "bob", "at": datetime(2026, 10, 19, 10, 50), "summary": "Bob's secret."},
    ]
    asyncio.run(app.state.mongo["portfolio_snapshots"].insert_many(snaps))
    assert client.get("/api/v1/mine/review/latest").json() == {"text": "Latest review.", "date": "2026-10-19"}
    app.dependency_overrides[get_current_user] = lambda: _user("carol")
    assert client.get("/api/v1/mine/review/latest").status_code == 404


def test_note_returns_cache_only(client, monkeypatch):
    assert client.get("/api/v1/research/TCS/note").status_code == 404
    note = {"summary": "TCS steady.", "thesis": "Margins hold.", "news_articles": []}
    monkeypatch.setattr(database.db, "redis", Redis({"analyst:TCS": json.dumps(note)}, ttl=3600))
    body = client.get("/api/v1/research/tcs/note").json()
    assert body["summary"] == "TCS steady." and body["thesis"] == "Margins hold." and body["as_of"]
    monkeypatch.setattr(database.db, "redis", Redis({"analyst:TCS": json.dumps({"summary": "Unable to generate summary."})}))
    assert client.get("/api/v1/research/TCS/note").status_code == 404
