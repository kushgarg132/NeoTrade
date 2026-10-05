from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.learning.library import catalog, strategy_names
from backend.routers import settings as settings_router
from backend.tests.test_settings_router import _user

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


async def test_catalog_for_a_new_user_has_every_strategy_and_empty_stats(mongo):
    cards = await catalog(mongo, "alice", [])
    assert [c["name"] for c in cards] == sorted(strategy_names())
    assert {"gap_and_go", "gap_fill_fade", "trend_day_pullback", "relative_strength_sector"} <= {c["name"] for c in cards}
    for c in cards:
        assert c["backtest"] is None and c["stats"]["all"] is None
        assert c["learned"] == {"paused": False, "floor": None, "skip_regimes": []}
        assert c["card"]["regimes"] and c["live_switch"] is False


async def test_catalog_joins_gate_paper_learning_and_attribution(mongo):
    await mongo["strategy_backtests"].insert_one({
        "strategy_name": "orb_breakout", "run_at": NOW, "passed": True,
        "result": {"total_trades": 80, "profit_factor": 1.6, "max_drawdown": 0.08}})
    await mongo["learning_state"].insert_one({
        "user_id": "alice", "paused": {"vwap_reversion": NOW}, "floors": {"orb_breakout": 0.6},
        "skip_regimes": {"orb_breakout": ["down"]}})
    await mongo["paper_trades"].insert_many([{
        "user_id": "alice", "venue": "paper", "status": "CLOSED", "strategy": "orb_breakout",
        "realized_pnl": 100.0 if i % 2 else -50.0, "costs": 5.0,
        "entry_at": NOW - timedelta(days=20 - i, hours=1), "exit_at": NOW - timedelta(days=20 - i),
        "context": {"strength": 0.7, "reason_codes": ["orb_breakout"]}} for i in range(12)])
    by_name = {c["name"]: c for c in await catalog(mongo, "alice", [])}
    orb = by_name["orb_breakout"]
    assert orb["backtest"]["passed"] is True and orb["backtest"]["profit_factor"] == 1.6
    assert orb["stats"]["all"]["trades"] == 12 and "orb_breakout" in orb["stats"]["by_reason"]
    assert orb["learned"] == {"paused": False, "floor": 0.6, "skip_regimes": ["down"]}
    assert orb["paper"]["passed"] is False and orb["paper"]["checks"]
    assert by_name["vwap_reversion"]["learned"]["paused"] is True


async def test_catalog_filters_by_mode(mongo):
    cards = await catalog(mongo, "alice", [], mode="LONGTERM")
    assert cards and all(c["mode"] == "LONGTERM" for c in cards)


def test_library_route_returns_the_users_catalog(mongo, monkeypatch):
    monkeypatch.setattr(settings_router.db, "db", mongo)

    async def no_nifty():
        return []

    monkeypatch.setattr("backend.portfolio.service._nifty", no_nifty)
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user()
    response = TestClient(app).get("/api/v1/strategies/library", params={"mode": "INTRADAY"})
    assert response.status_code == 200
    names = [c["name"] for c in response.json()["strategies"]]
    assert "gap_and_go" in names and "macd_crossover" not in names


async def test_chat_tool_reads_the_library(mongo, monkeypatch):
    import json

    from backend.chat.tools import read_tools

    async def no_nifty():
        return []

    monkeypatch.setattr("backend.portfolio.service._nifty", no_nifty)
    tool = next(t for t in read_tools(mongo, None, "alice") if t.name == "get_strategy_library")
    cards = json.loads(await tool.ainvoke({"mode": "INTRADAY"}))
    assert "gap_and_go" in [c["name"] for c in cards] and all(c["mode"] == "INTRADAY" for c in cards)
