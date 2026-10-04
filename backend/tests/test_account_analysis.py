"""Analysis per account: the AI's (Kite) and the user's own (Upstox), apart
and side by side."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.journal import accounts

T0 = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)
ROLES = {"kite": "ai", "upstox": "mine"}


def _fill(i, broker, side, price, at, symbol="INFY", qty=10):
    return {"_id": f"t{i}", "broker": broker, "exchange": "NSE", "symbol": symbol, "side": side,
            "quantity": qty, "price": price, "traded_at": at}


def _trades():
    return [
        _fill(1, "kite", "BUY", 100.0, T0), _fill(2, "kite", "SELL", 110.0, T0 + timedelta(hours=2)),
        _fill(3, "upstox", "BUY", 200.0, T0), _fill(4, "upstox", "SELL", 190.0, T0 + timedelta(hours=2)),
        _fill(5, "kite", "BUY", 100.0, T0 + timedelta(days=31)),
        _fill(6, "kite", "SELL", 120.0, T0 + timedelta(days=31, hours=1)),
    ]


def test_filter_trades_by_account():
    assert {t["broker"] for t in accounts.filter_trades(_trades(), {"upstox"})} == {"upstox"}
    assert len(accounts.filter_trades(_trades(), None)) == 6


def test_ai_vs_me_by_month():
    nifty = [(date(2026, 8, 1), 24000.0), (date(2026, 8, 31), 24480.0),
             (date(2026, 9, 1), 24480.0), (date(2026, 9, 30), 24000.0)]
    rows = accounts.ai_vs_me(_trades(), ROLES, {"ai": 25_000.0, "mine": 100_000.0}, nifty)
    by_month = {r["month"]: r for r in rows}
    aug, sep = by_month["2026-08"], by_month["2026-09"]
    assert aug["ai"]["gross_pnl"] == pytest.approx(100.0) and aug["mine"]["gross_pnl"] == pytest.approx(-100.0)
    assert aug["ai"]["net_pnl"] < 100.0  # charges taken off
    assert aug["nifty_return"] == pytest.approx(0.02)
    assert sep["mine"]["fills"] == 0 and sep["ai"]["gross_pnl"] == pytest.approx(200.0)
    assert sep["ai"]["return"] == pytest.approx(sep["ai"]["net_pnl"] / 25_000.0)


def test_portfolio_account_view_keeps_only_that_brokers_holdings():
    from backend.portfolio.service import scorecard_for

    snapshot = {
        "holdings": [{"symbol": "INFY", "verdict": "HOLD", "sector": "IT"}, {"symbol": "TCS", "verdict": "ADD", "sector": "IT"}],
        "raw_holdings": [
            {"broker": "kite", "symbol": "INFY", "exchange": "NSE", "isin": "I1", "kind": "STOCK", "quantity": 10,
             "avg_price": 1400.0, "last_price": 1500.0, "close_price": 1490.0},
            {"broker": "upstox", "symbol": "TCS", "exchange": "NSE", "isin": "I2", "kind": "STOCK", "quantity": 5,
             "avg_price": 3000.0, "last_price": 3100.0, "close_price": 3090.0},
        ],
    }
    view = scorecard_for(snapshot, {"upstox"}, trades=[], nifty=[])
    assert [r["symbol"] for r in view["holdings"]] == ["TCS"]
    assert view["totals"]["value"] == pytest.approx(15_500.0)
    assert view["holdings"][0]["verdict"] == "ADD"  # the full review's verdict carries over


def _journal_app(monkeypatch, trades):
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient

    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.journal.store import JournalStore
    from backend.routers import journal as journal_router

    mock_db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(journal_router.db, "db", mock_db)
    monkeypatch.setattr(journal_router.db, "redis", None)

    async def no_brokers(*_a):
        return []

    monkeypatch.setattr(journal_router, "connected_brokers", no_brokers)
    asyncio.run(mock_db["journal_trades"].insert_many([{**t, "user_id": "alice"} for t in trades]))
    asyncio.run(mock_db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": ROLES}))
    app = FastAPI()
    app.include_router(journal_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                               created_at=T0)
    app.dependency_overrides[journal_router.get_journal_store] = lambda: JournalStore(mock_db)
    app.dependency_overrides[journal_router.get_nifty] = lambda: [(date(2026, 8, 1), 24000.0), (date(2026, 9, 30), 24000.0)]
    return TestClient(app), mock_db


def test_journal_endpoint_filters_by_account(monkeypatch):
    client, _ = _journal_app(monkeypatch, _trades())
    mine = client.get("/api/v1/journal?account=mine").json()
    assert {t["broker"] for t in mine["round_trips"]} == {"upstox"}
    assert mine["mirror"]["costs"]["fills"] == 2
    assert len(client.get("/api/v1/journal").json()["round_trips"]) == 3
    rows = client.get("/api/v1/journal/ai-vs-me").json()
    assert [r["month"] for r in rows] == ["2026-08", "2026-09"]


async def test_get_journal_tool_takes_an_account():
    import json

    from mongomock_motor import AsyncMongoMockClient

    from backend.chat.tools import read_tools

    db = AsyncMongoMockClient()["test_db"]
    await db["journal_trades"].insert_many([{**t, "user_id": "alice"} for t in _trades()])
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": ROLES})
    tool = next(t for t in read_tools(db, None, "alice") if t.name == "get_journal")
    out = json.loads(await tool.ainvoke({"period": "all", "account": "ai"}))
    assert out["account"] == "ai" and out["closed"] == 2


async def test_get_portfolio_tool_takes_an_account(monkeypatch):
    import json

    from mongomock_motor import AsyncMongoMockClient

    import backend.chat.tools as tools_module
    from backend.chat.tools import read_tools

    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": ROLES})
    await db["portfolio_snapshots"].insert_one({
        "user_id": "alice", "at": T0, "holdings": [], "totals": {}, "raw_holdings": [
            {"broker": "kite", "symbol": "INFY", "exchange": "NSE", "kind": "STOCK", "quantity": 10,
             "avg_price": 1400.0, "last_price": 1500.0, "close_price": 1490.0},
            {"broker": "upstox", "symbol": "TCS", "exchange": "NSE", "kind": "STOCK", "quantity": 5,
             "avg_price": 3000.0, "last_price": 3100.0, "close_price": 3090.0}]})

    async def no_nifty():
        return []

    monkeypatch.setattr("backend.portfolio.service._nifty", no_nifty)
    tool = next(t for t in read_tools(db, None, "alice") if t.name == "get_portfolio")
    out = json.loads(await tool.ainvoke({"account": "ai"}))
    assert [h["symbol"] for h in out["holdings"]] == ["INFY"] and out["account"] == "ai"
