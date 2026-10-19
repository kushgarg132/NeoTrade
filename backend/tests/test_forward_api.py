"""GET /forward/scorecard and /forward/records: admin only."""

import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import forward as forward_router

NOW = datetime.now(timezone.utc)


def _rec(i, source, name):
    return {"_id": f"{source}:{name}:S{i}:2026-01-0{i}:BUY", "source": source, "name": name, "user_id": "system",
            "symbol": f"S{i}", "side": "BUY", "decided_at": NOW, "predicted": None, "scored_at": NOW,
            "outcome": {"net": 0.01, "nifty": 0.0, "excess": 0.01 * i, "won": True}}


def _client(monkeypatch, role="admin"):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(forward_router.db, "db", db)
    asyncio.run(db["forward_records"].insert_many([_rec(1, "picks", "a"), _rec(2, "picks", "a"), _rec(3, "engine", "b")]))
    app = FastAPI()
    app.include_router(forward_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW, role=role)
    return TestClient(app)


def test_scorecard_rows_carry_label_fields(monkeypatch):
    rows = _client(monkeypatch).get("/api/v1/forward/scorecard").json()["rows"]
    a = next(r for r in rows if r["name"] == "a")
    assert a["source"] == "picks" and a["n"] == 2 and a["label"] == "unproven" and a["progress"] == 2


def test_records_filter_by_source(monkeypatch):
    recs = _client(monkeypatch).get("/api/v1/forward/records?source=picks").json()["records"]
    assert len(recs) == 2 and all(r["source"] == "picks" and "_id" not in r and r["id"] for r in recs)


def test_non_admin_is_refused(monkeypatch):
    client = _client(monkeypatch, role="user")
    assert client.get("/api/v1/forward/scorecard").status_code == 403
    assert client.get("/api/v1/forward/records").status_code == 403
