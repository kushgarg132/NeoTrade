"""GET /mine/stock/{symbol}, as the signed-in user only."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.portfolio import service
from backend.routers import mine as mine_router
from backend.routers import portfolio as portfolio_router

NOW = datetime.now(timezone.utc)


def _trade(side, qty, price, days_ago, symbol="INFY", user="alice"):
    return {"user_id": user, "symbol": symbol, "side": side, "quantity": qty, "price": price,
            "broker": "upstox", "traded_at": NOW - timedelta(days=days_ago)}


def _snap(days_ago, verdict, raw=True):
    holding = {"symbol": "INFY", "verdict": verdict, "reason_codes": ["uptrend"], "note": "n"}
    doc = {"user_id": "alice", "at": NOW - timedelta(days=days_ago), "holdings": [holding]}
    if raw:
        doc["raw_holdings"] = [{"symbol": "INFY", "kind": "STOCK", "quantity": 10, "avg_price": 100.0,
                                "broker": "upstox", "last_price": 150.0}]
    return doc


@pytest.fixture
def setup(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(mine_router.db, "db", db)
    monkeypatch.setattr(portfolio_router.db, "db", db)

    async def quoted(db_, raw, now, read_at=None):
        return raw, True

    monkeypatch.setattr(service, "quoted", quoted)
    visible = {"v": True}

    async def vis(user):
        return visible["v"]

    monkeypatch.setattr(portfolio_router, "verdicts_visible_to", vis)
    app = FastAPI()
    app.include_router(mine_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW)

    def seed(collection, rows):
        asyncio.run(db[collection].insert_many(rows))

    return TestClient(app), seed, visible


def test_held_position_and_lots(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 4, 100, 400), _trade("BUY", 6, 100, 30), _trade("BUY", 5, 1, 1, user="bob")])
    seed("portfolio_snapshots", [_snap(0, "HOLD")])
    body = client.get("/api/v1/mine/stock/infy").json()
    assert body["position"]["qty"] == 10 and body["position"]["sold"] is False
    assert body["position"]["value"] == 1500 and body["position"]["pnl"] == 500
    long_lot, short_lot = body["lots"]
    assert long_lot["days_to_long"] == 0 and long_lot["est_tax"] == pytest.approx(0.125 * 200)
    assert short_lot["days_to_long"] == 336 and short_lot["est_tax"] == pytest.approx(0.2 * 300)
    assert body["unknown_qty"] == 0 and len(body["trades"]) == 2
    assert body["verdict"]["current"] == "HOLD" and body["verdict"]["reasons"] == ["uptrend"]


def test_sold_symbol_still_opens(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 5, 100, 50), _trade("SELL", 5, 120, 10)])
    body = client.get("/api/v1/mine/stock/INFY").json()
    assert body["position"]["sold"] is True and body["position"]["qty"] == 0
    assert body["position"]["pnl"] == 100 and len(body["trades"]) == 2 and body["lots"] == []


def test_unknown_symbol_404(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 5, 100, 50, user="bob")])
    assert client.get("/api/v1/mine/stock/INFY").status_code == 404
    assert client.get("/api/v1/mine/stock/bad%20sym").status_code == 422


def test_verdict_history_only_changes(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 1, 100, 5)])
    seed("portfolio_snapshots", [_snap(3, "HOLD"), _snap(2, "HOLD"), _snap(1, "SELL", raw=False)])
    hist = client.get("/api/v1/mine/stock/INFY").json()["verdict"]["history"]
    assert [h["verdict"] for h in hist] == ["HOLD", "SELL"]


def test_verdict_masked_without_visibility(setup):
    client, seed, visible = setup
    visible["v"] = False
    seed("journal_trades", [_trade("BUY", 1, 100, 5)])
    seed("portfolio_snapshots", [_snap(2, "HOLD"), _snap(1, "SELL")])
    v = client.get("/api/v1/mine/stock/INFY").json()["verdict"]
    assert v["current"] == "REVIEW" and v["note"] == "n"
    assert v["history"] == [{"date": v["history"][0]["date"], "verdict": "REVIEW"}]


def test_news_for_symbol_newest_first(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 1, 100, 5)])
    seed("news_items", [
        {"title": f"n{i}", "published_at": NOW - timedelta(hours=i), "impacts": [{"target": "INFY", "direction": "UP", "impact": 0.5}]}
        for i in range(12)] + [{"title": "other", "published_at": NOW, "impacts": [{"target": "TCS"}]}])
    news = client.get("/api/v1/mine/stock/INFY").json()["news"]
    assert len(news) == 10 and news[0]["title"] == "n0"


# ---- final-review fixes (I7, I2, I3)


def _held(qty, avg, last):
    return {"user_id": "alice", "at": NOW, "holdings": [],
            "raw_holdings": [{"symbol": "INFY", "kind": "STOCK", "quantity": qty, "avg_price": avg,
                              "broker": "upstox", "last_price": last}]}


def test_xirr_counts_only_shares_with_a_known_buy(setup):
    """I7: journal 10 @100 a year ago, broker 100 (90 from before the journal): ~10%, not ~1000%."""
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 10, 100, 365)])
    seed("portfolio_snapshots", [_held(100, 50, 110)])
    body = client.get("/api/v1/mine/stock/INFY").json()
    assert body["unknown_qty"] == 90
    assert body["position"]["xirr"] == pytest.approx(0.10, abs=0.01)


def test_xirr_none_when_no_share_has_a_known_buy(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 5, 100, 400), _trade("SELL", 5, 150, 300)])
    seed("portfolio_snapshots", [_held(10, 80, 110)])
    assert client.get("/api/v1/mine/stock/INFY").json()["position"]["xirr"] is None


def test_bonus_scales_lots_and_trade_markers(setup):
    """I2/I3: 1:1 bonus after the journal's buy -- bars are adjusted, so markers must be too."""
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 10, 200, 400)])
    seed("portfolio_snapshots", [_held(20, 100, 120)])
    body = client.get("/api/v1/mine/stock/INFY").json()
    assert body["unknown_qty"] == 0 and body["lots"][0]["qty"] == 20 and body["lots"][0]["price"] == 100
    assert body["trades"] == [{"date": body["trades"][0]["date"], "side": "BUY", "qty": 20, "price": 100}]


def test_held_without_a_price_has_unknown_pnl_not_realised(setup):
    client, seed, _ = setup
    seed("journal_trades", [_trade("BUY", 10, 100, 400), _trade("SELL", 5, 150, 300)])
    seed("portfolio_snapshots", [_held(5, 100, None)])
    body = client.get("/api/v1/mine/stock/INFY").json()["position"]
    assert body["value"] is None and body["pnl"] is None and body["pnl_pct"] is None
