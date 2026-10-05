"""/portfolio/rebalance, its candidates, saved targets and the AI row actions
on GET /portfolio (docs/superpowers/specs/2026-10-05-portfolio-rebalance-design.md)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.portfolio.rebalance import plan_rebalance
from backend.routers import portfolio as portfolio_router


def _user(user_id="alice", role="user"):
    return User(id=user_id, google_sub=f"sub-{user_id}", email=f"{user_id}@example.com", name=user_id.title(),
                picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), role=role)


def _row(symbol, value, verdict="HOLD", price=100.0, kind="STOCK"):
    return {"symbol": symbol, "kind": kind, "sector": "IT", "quantity": value / price, "last_price": price,
            "close_price": price, "verdict": verdict, "value": value}


ROWS = [_row("A", 80_000, "SELL"), _row("B", 20_000, "ADD"), _row("C", 20_000, "HOLD")]


@pytest.fixture
def mdb(monkeypatch):
    database = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(portfolio_router, "db", SimpleNamespace(db=database, redis=None))
    return database


def _client(user):
    app = FastAPI()
    app.include_router(portfolio_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


async def _snapshot(mdb, user_id="alice", rows=ROWS):
    await mdb["portfolio_snapshots"].insert_one({"user_id": user_id, "at": datetime.now(timezone.utc),
                                                 "holdings": [dict(r) for r in rows], "brokers": ["kite"]})


def test_rebalance_needs_a_snapshot(mdb):
    response = _client(_user()).post("/api/v1/portfolio/rebalance", json={"new_money": 0})
    assert response.status_code == 409 and response.json()["detail"] == "Refresh your portfolio first"


async def test_rebalance_reads_only_own_snapshot(mdb):
    await _snapshot(mdb, user_id="bob")
    assert _client(_user()).post("/api/v1/portfolio/rebalance", json={"new_money": 0}).status_code == 409


async def test_rebalance_returns_trades_and_uses_saved_targets(mdb):
    await _snapshot(mdb)
    targets = {"rule": "equal", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}
    await mdb["user_prefs"].insert_one({"user_id": "alice", "rebalance_targets": targets})
    body = _client(_user()).post("/api/v1/portfolio/rebalance", json={"new_money": 0}).json()
    expected = plan_rebalance(ROWS, [], targets, 0, {}, datetime.now(timezone.utc).date())
    assert [(t["symbol"], t["side"], t["quantity"]) for t in body["trades"]] == \
        [(t["symbol"], t["side"], t["quantity"]) for t in expected["trades"]]
    assert body["stale_since"] is None


def test_overrides_over_100_rejected(mdb):
    response = _client(_user()).post("/api/v1/portfolio/rebalance", json={
        "new_money": 0, "targets": {"rule": "cap", "overrides": {"A": 60, "B": 50}}})
    assert response.status_code == 422


def test_too_many_candidates_rejected(mdb):
    response = _client(_user()).post("/api/v1/portfolio/rebalance",
                                     json={"new_money": 0, "candidates": [f"S{i}" for i in range(21)]})
    assert response.status_code == 422


async def test_candidates_hide_ai_picks_when_verdicts_hidden(mdb, monkeypatch):
    await _snapshot(mdb)
    await mdb["watchlist"].insert_one({"user_id": "alice", "symbols": ["W1", "A"]})
    await mdb["suggestions"].insert_one({"user_id": "alice", "status": "PENDING", "mode": "LONGTERM", "symbol": "P1", "side": "BUY"})

    async def closes(symbols):
        return {s: 50.0 for s in symbols}
    monkeypatch.setattr(portfolio_router, "_closes", closes)

    body = _client(_user()).get("/api/v1/portfolio/rebalance/candidates").json()
    assert body == [{"symbol": "W1", "price": 50.0, "source": "watchlist"}]
    admin = _client(_user(role="admin")).get("/api/v1/portfolio/rebalance/candidates").json()
    assert {(c["symbol"], c["source"]) for c in admin} == {("W1", "watchlist"), ("P1", "ai")}


async def test_get_portfolio_adds_suggested_for_admin_and_nulls_for_others(mdb):
    await _snapshot(mdb)
    await mdb["user_prefs"].insert_one({"user_id": "alice", "rebalance_targets": {
        "rule": "equal", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}})
    rows = {r["symbol"]: r for r in _client(_user(role="admin")).get("/api/v1/portfolio").json()["holdings"]}
    assert rows["A"]["suggested"] == {"side": "SELL", "quantity": 800, "price": 100.0}
    assert rows["B"]["suggested"]["side"] == "BUY" and rows["B"]["suggested"]["quantity"] > 0
    assert rows["C"]["suggested"] is None
    hidden = _client(_user()).get("/api/v1/portfolio").json()["holdings"]
    assert all(r["suggested"] is None for r in hidden)


async def test_add_at_target_has_no_trade(mdb):
    await _snapshot(mdb, rows=[_row("A", 50_000, "ADD"), _row("B", 50_000, "HOLD")])
    await mdb["user_prefs"].insert_one({"user_id": "alice", "rebalance_targets": {
        "rule": "equal", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}})
    rows = {r["symbol"]: r for r in _client(_user(role="admin")).get("/api/v1/portfolio").json()["holdings"]}
    assert rows["A"]["suggested"] == {"at_target": True}


async def test_rebalance_rate_limited(mdb, monkeypatch):
    await _snapshot(mdb)

    async def refuse(*args, **kwargs):
        return False
    monkeypatch.setattr(portfolio_router, "allow", refuse)
    assert _client(_user()).post("/api/v1/portfolio/rebalance", json={"new_money": 0}).status_code == 429


async def test_rebalance_uses_only_my_account_when_roles_are_set(mdb):
    raw = [{"symbol": "MINE1", "quantity": 800, "avg_price": 90.0, "last_price": 100.0, "close_price": 100.0, "broker": "kite"},
           {"symbol": "MINE2", "quantity": 200, "avg_price": 90.0, "last_price": 100.0, "close_price": 100.0, "broker": "kite"},
           {"symbol": "AI1", "quantity": 5000, "avg_price": 90.0, "last_price": 100.0, "close_price": 100.0, "broker": "upstox"}]
    rows = [_row("MINE1", 80_000), _row("MINE2", 20_000), _row("AI1", 500_000)]
    await mdb["portfolio_snapshots"].insert_one({"user_id": "alice", "at": datetime.now(timezone.utc),
                                                 "holdings": rows, "raw_holdings": raw, "brokers": ["kite", "upstox"]})
    await mdb["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"kite": "mine", "upstox": "ai"},
                                        "rebalance_targets": {"rule": "equal", "max_stock_pct": 15,
                                                              "max_sector_pct": 30, "overrides": {}}})
    body = _client(_user()).post("/api/v1/portfolio/rebalance", json={"new_money": 0}).json()
    assert {t["symbol"] for t in body["trades"]} == {"MINE1", "MINE2"}
    assert body["total"] == pytest.approx(100_000)


async def test_candidates_skip_ai_sell_suggestions(mdb, monkeypatch):
    await _snapshot(mdb)
    await mdb["suggestions"].insert_many([
        {"user_id": "alice", "status": "PENDING", "mode": "LONGTERM", "symbol": "P1", "side": "BUY"},
        {"user_id": "alice", "status": "PENDING", "mode": "LONGTERM", "symbol": "X1", "side": "SELL"}])

    async def closes(symbols):
        return {s: 50.0 for s in symbols}
    monkeypatch.setattr(portfolio_router, "_closes", closes)
    admin = _client(_user(role="admin")).get("/api/v1/portfolio/rebalance/candidates").json()
    assert [c["symbol"] for c in admin] == ["P1"]


@pytest.mark.parametrize("body", [
    {"new_money": "Infinity"}, {"new_money": 1e13},
    {"new_money": 0, "targets": {"rule": "cap", "max_stock_pct": "NaN"}},
])
def test_unbounded_numbers_rejected(mdb, body):
    assert _client(_user()).post("/api/v1/portfolio/rebalance", json=body).status_code == 422
