"""GET /journal/round-trips/{id}: one round trip with fills, note, news and findings."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.journal.store import JournalStore
from backend.routers import journal as journal_router

T0 = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)


def _fill(uid, i, side, price):
    return {"_id": f"{uid}:kite:{i}", "user_id": uid, "broker": "kite", "exchange": "NSE", "symbol": "INFY",
            "side": side, "quantity": 10, "price": price, "traded_at": T0 + timedelta(hours=i)}


def _client(monkeypatch, fills):
    mock_db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(journal_router.db, "db", mock_db)
    asyncio.run(mock_db["journal_trades"].insert_many(fills))
    app = FastAPI()
    app.include_router(journal_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u1", google_sub="g", email="a@x.io", name="A", created_at=T0)
    app.dependency_overrides[journal_router.get_journal_store] = lambda: JournalStore(mock_db)
    return TestClient(app)


def test_round_trip_by_id(monkeypatch):
    c = _client(monkeypatch, [_fill("u1", 1, "BUY", 100.0), _fill("u1", 2, "SELL", 110.0)])
    r = c.get("/api/v1/journal/round-trips/u1%3Akite%3A1")
    assert r.status_code == 200
    body = r.json()
    assert body["pnl"] == 100.0
    assert len(body["fills"]) == 2
    assert {"note", "tags", "news", "exit_news", "insights"} <= body.keys()


def test_open_round_trip_has_null_pnl(monkeypatch):
    c = _client(monkeypatch, [_fill("u1", 1, "BUY", 100.0)])
    r = c.get("/api/v1/journal/round-trips/u1%3Akite%3A1")
    assert r.status_code == 200 and r.json()["pnl"] is None


def test_other_users_round_trip_is_404(monkeypatch):
    c = _client(monkeypatch, [_fill("u2", 1, "BUY", 100.0), _fill("u2", 2, "SELL", 110.0)])
    r = c.get("/api/v1/journal/round-trips/u2%3Akite%3A1")
    assert r.status_code == 404 and r.json()["detail"] == "Round trip not found"
