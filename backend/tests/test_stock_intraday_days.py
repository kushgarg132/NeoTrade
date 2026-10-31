"""GET /agents/intraday/{symbol}?days=1|5: the stock chart's 1D (1d at 5m) and 1W (5d at 15m) feeds."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.datalayer import stock_info
from backend.routers import agents


@pytest.fixture
def http(monkeypatch):
    seen = []

    async def fake(symbol, period="1mo", interval="1d"):
        seen.append((period, interval))
        return [], "test"

    monkeypatch.setattr(stock_info, "fetch_price_history_logic", fake)
    app = FastAPI()
    app.include_router(agents.router, prefix="/agents")
    return TestClient(app), seen


def test_default_is_one_session_at_five_minutes(http):
    client, seen = http
    assert client.get("/agents/intraday/INFY").status_code == 200
    assert seen == [("1d", "5m")]


def test_days_5_is_five_sessions_at_fifteen_minutes(http):
    client, seen = http
    assert client.get("/agents/intraday/INFY?days=5").status_code == 200
    assert seen == [("5d", "15m")]


def test_other_days_are_422(http):
    client, seen = http
    assert client.get("/agents/intraday/INFY?days=3").status_code == 422
    assert seen == []
