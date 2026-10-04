"""GET /today: one call for the Today page -- what needs the user, whose
money is where, and how far setup has got. Each part fails on its own."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.routers import today as today_router

NOW = datetime.now(timezone.utc)


def _client(monkeypatch, states=None, broken=False):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(today_router.db, "db", db)
    monkeypatch.setattr(today_router.db, "redis", None)

    async def broker_states(user_id, brokers):
        if broken:
            raise RuntimeError("broker API down")
        return {b: (states or {}).get(b, "NEEDS_LOGIN") for b in brokers}

    app = FastAPI()
    app.include_router(today_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW)
    app.dependency_overrides[today_router.get_broker_states] = lambda: broker_states
    return TestClient(app), db


def _seed(db, **docs):
    for collection, rows in docs.items():
        asyncio.run(db[collection].insert_many(rows))


def test_fresh_user_has_an_empty_setup_and_no_login_nags(monkeypatch):
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/today").json()
    assert body["setup"]["done"] == 0 and body["setup"]["total"] == 6
    assert not [n for n in body["needs_you"] if n["kind"] == "login"]
    assert body["accounts"] == {}


def test_login_needed_for_a_role_whose_broker_is_logged_out(monkeypatch):
    client, db = _client(monkeypatch, states={"upstox": "ACTIVE"})
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}}])
    body = client.get("/api/v1/today").json()
    logins = [n for n in body["needs_you"] if n["kind"] == "login"]
    assert len(logins) == 1 and logins[0]["link"] == "/settings?tab=accounts" and "Kite" in logins[0]["title"]
    assert body["accounts"]["ai"] == {"broker": "kite", "state": "NEEDS_LOGIN"}
    assert body["accounts"]["mine"]["state"] == "ACTIVE"


def test_needs_you_orders_proposals_by_expiry_and_includes_cards(monkeypatch):
    client, db = _client(monkeypatch)
    _seed(db, suggestions=[
        {"id": "late", "user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 1, "expires_at": NOW + timedelta(days=3), "created_at": NOW},
        {"id": "soon", "user_id": "alice", "symbol": "SJVN", "side": "BUY", "status": "PENDING", "mode": "LONGTERM",
         "quantity": 1, "expires_at": NOW + timedelta(days=1), "created_at": NOW},
    ], chat_actions=[{"id": "c1", "user_id": "alice", "status": "PROPOSED", "summary": "Sell 10 INFY",
                      "expires_at": NOW + timedelta(minutes=10), "created_at": NOW}])
    items = client.get("/api/v1/today").json()["needs_you"]
    proposals = [n["title"] for n in items if n["kind"] == "proposal"]
    assert proposals.index(next(t for t in proposals if "SJVN" in t)) < proposals.index(next(t for t in proposals if "TCS" in t))
    assert any(n["kind"] == "card" and "Sell 10 INFY" in n["title"] for n in items)


def test_pnl_today_splits_mine_and_ai(monkeypatch):
    client, db = _client(monkeypatch)
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}}],
          journal_trades=[
              {"_id": "t1", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "INFY",
               "side": "BUY", "quantity": 10, "price": 100.0, "traded_at": NOW - timedelta(minutes=30)},
              {"_id": "t2", "user_id": "alice", "broker": "upstox", "exchange": "NSE", "symbol": "INFY",
               "side": "SELL", "quantity": 10, "price": 110.0, "traded_at": NOW - timedelta(minutes=5)}],
          paper_trades=[{"user_id": "alice:autopilot", "symbol": "TCS", "side": "BUY", "status": "CLOSED",
                         "realized_pnl": -50.0, "exit_at": NOW - timedelta(minutes=1), "venue": "paper"}])
    assert client.get("/api/v1/today").json()["pnl_today"] == {"mine": 100.0, "ai": -50.0}


def test_a_failing_part_degrades_not_errors(monkeypatch):
    client, db = _client(monkeypatch, broken=True)
    _seed(db, user_prefs=[{"user_id": "alice", "broker_roles": {"kite": "ai"}}])
    resp = client.get("/api/v1/today")
    assert resp.status_code == 200
    assert resp.json()["accounts"] is None and "accounts" in resp.json()["errors"]
