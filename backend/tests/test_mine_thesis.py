"""GET/PUT /mine/thesis/{symbol}, as the signed-in user only."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import mine as mine_router

URL = "/api/v1/mine/thesis/"


@pytest.fixture
def setup(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(mine_router.db, "db", db)
    app = FastAPI()
    app.include_router(mine_router.router, prefix="/api/v1")
    holder = {"user": "alice"}
    app.dependency_overrides[get_current_user] = lambda: User(
        id=holder["user"], google_sub="g", email="a@x.io", name="A", created_at=datetime.now(timezone.utc))
    return TestClient(app), db, holder


def test_put_then_get_roundtrip(setup):
    client, _, _ = setup
    assert client.get(URL + "infy").json() == {}
    body = {"why": "moat", "target": 2000, "stop": 1400, "review_by": "2027-01-15"}
    saved = client.put(URL + "infy", json=body).json()
    assert "_id" not in saved and saved["symbol"] == "INFY" and saved["updated_at"]
    got = client.get(URL + "INFY").json()
    assert got["why"] == "moat" and got["target"] == 2000 and got["review_by"] == "2027-01-15"


def test_stop_above_target_422(setup):
    client, _, _ = setup
    assert client.put(URL + "INFY", json={"target": 100, "stop": 150}).status_code == 422
    assert client.put(URL + "INFY", json={"target": 100, "stop": 100}).status_code == 422


def test_negative_price_422(setup):
    client, _, _ = setup
    assert client.put(URL + "INFY", json={"target": -1}).status_code == 422
    assert client.put(URL + "INFY", json={"stop": 0}).status_code == 422


def test_why_too_long_422(setup):
    assert setup[0].put(URL + "INFY", json={"why": "x" * 2001}).status_code == 422


def test_bad_symbol_422(setup):
    client, _, _ = setup
    assert client.put(URL + "BAD%20SYM", json={}).status_code == 422
    assert client.get(URL + "A" * 21).status_code == 422


def test_user_b_cannot_read_a(setup):
    client, _, holder = setup
    client.put(URL + "INFY", json={"why": "mine"})
    holder["user"] = "bob"
    assert client.get(URL + "INFY").json() == {}


def test_put_twice_updates_not_duplicates(setup):
    import asyncio
    client, db, _ = setup
    client.put(URL + "INFY", json={"why": "one"})
    client.put(URL + "INFY", json={"why": "two"})
    assert asyncio.run(db["holding_theses"].count_documents({})) == 1
    assert client.get(URL + "INFY").json()["why"] == "two"
