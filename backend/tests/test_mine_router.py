"""GET /mine/overview and /mine/history, as the signed-in user only."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.engine.session import IST
from backend.portfolio import digest
from backend.routers import mine as mine_router

NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(IST).date()
MONTH_END_BEFORE = TODAY.replace(day=1) - timedelta(days=1)


def _row(user, day, value, **extra):
    return {"user_id": user, "date": day.isoformat(), "value": value, "invested": 2000, "nifty_value": 2100,
            "flow": 0, "by_symbol": {}, "partial": False, **extra}


@pytest.fixture
def setup(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(mine_router.db, "db", db)
    app = FastAPI()
    app.include_router(mine_router.router, prefix="/api/v1")
    holder = {"user": "alice"}
    app.dependency_overrides[get_current_user] = lambda: User(
        id=holder["user"], google_sub="g", email="a@x.io", name="A", created_at=NOW)
    return TestClient(app), db, holder


def _seed(db, collection, rows):
    import asyncio
    asyncio.run(db[collection].insert_many(rows))


def test_history_range_filters(setup):
    client, db, _ = setup
    _seed(db, "mine_daily", [_row("alice", TODAY - timedelta(days=d), 2000 - d) for d in (40, 10, 0)] +
          [_row("bob", TODAY, 1)])
    body = client.get("/api/v1/mine/history?range=1M").json()
    assert [p["value"] for p in body["points"]] == [1990, 2000]
    assert body["from_date"] == (TODAY - timedelta(days=10)).isoformat() and body["partial"] is False
    assert len(client.get("/api/v1/mine/history?range=ALL").json()["points"]) == 3


def test_history_bad_range_422(setup):
    assert setup[0].get("/api/v1/mine/history?range=5Y").status_code == 422


def test_overview_drivers_month(setup, monkeypatch):
    client, db, _ = setup
    _seed(db, "mine_daily", [
        _row("alice", MONTH_END_BEFORE, 2000, by_symbol={"A": {"qty": 10, "value": 1000}, "B": {"qty": 10, "value": 1000}}),
        _row("alice", TODAY, 2600, by_symbol={"A": {"qty": 10, "value": 1300}, "B": {"qty": 15, "value": 1300}}),
    ])
    # B: 5 more shares bought this month at 100 -> 1300 - 1000 - 500 = -200; A: +300.
    _seed(db, "journal_trades", [{"user_id": "alice", "_id": "1", "symbol": "B", "side": "BUY", "quantity": 5, "price": 100,
                                  "broker": "upstox", "traded_at": datetime.combine(TODAY, datetime.min.time(), tzinfo=IST)}])
    _seed(db, "portfolio_snapshots", [{"user_id": "alice", "at": NOW, "concentration": {"top": 0.5}}])
    pulse = {"value": 2600.0, "day_change": 10.0, "day_change_pct": 0.4, "pnl": 600.0, "pnl_pct": 30.0,
             "as_of": NOW, "holdings_as_of": NOW, "pnl_by_symbol": {"A": 400.0, "B": 200.0, "C": -50.0}}
    monkeypatch.setattr(digest, "pulse", AsyncMock(return_value=pulse))
    body = client.get("/api/v1/mine/overview").json()
    assert body["drivers"]["month"] == {"top": [{"symbol": "A", "contribution": 300.0}],
                                        "bottom": [{"symbol": "B", "contribution": -200.0}]}
    assert [r["symbol"] for r in body["drivers"]["all"]["top"]] == ["A", "B"]
    assert body["drivers"]["all"]["bottom"] == [{"symbol": "C", "contribution": -50.0}]
    assert body["headline"]["value"] == 2600.0 and body["headline"]["xirr"] is None
    assert body["mix"] == {"top": 0.5}


def test_overview_other_user_sees_nothing(setup, monkeypatch):
    client, db, holder = setup
    _seed(db, "mine_daily", [_row("alice", TODAY, 2600, by_symbol={"A": {"qty": 1, "value": 5}})])
    monkeypatch.setattr(digest, "pulse", AsyncMock(return_value=None))
    holder["user"] = "bob"
    body = client.get("/api/v1/mine/overview").json()
    assert body["headline"] is None and body["mix"] is None
    assert body["drivers"] == {"month": {"top": [], "bottom": []}, "all": {"top": [], "bottom": []}}
