"""A tapped index opens an AI explanation of its latest session. The model
only writes prose: every figure it is given is gathered here first, and a
missing model is a clear 503, never a page of error text."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.components.shared.models import NewsArticle
from backend.research import index_move
from backend.routers import market_data


class _FakeTicker:
    def __init__(self, ticker):
        closes = [100.0 + i for i in range(20)]  # ... 118 then 119
        index = pd.date_range("2026-09-01", periods=20, freq="D")
        self._hist = pd.DataFrame({
            "Open": [c - 0.5 for c in closes], "High": [c + 1 for c in closes],
            "Low": [c - 2 for c in closes], "Close": closes,
        }, index=index)
        self._hist.iloc[-1, self._hist.columns.get_loc("Open")] = 120.0  # gap up

    def history(self, period, interval):
        return self._hist


def _article(title, hours_ago=1):
    return NewsArticle(title=title, url=f"https://x/{title}", source="Wire",
                       published_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago))


@pytest.fixture
def world(monkeypatch):
    index_move._cache.clear()
    calls = {"llm": [], "news": []}

    async def news(query, region="US", lang="en-US", limit=10):
        calls["news"].append((query, region))
        return [_article("RBI holds rates"), _article("rbi holds rates"), _article("Old story", hours_ago=90)]

    async def peers(symbol, name):
        return {"name": name, "symbol": symbol, "value": 1.0, "change": 0.1, "percent": 0.8}

    async def trending():
        return [{"symbol": "HDFCBANK.NS", "name": "HDFCBANK.NS", "value": 1.0, "percent": 2.5}]

    async def completion(prompt, system_prompt):
        calls["llm"].append((system_prompt, prompt))
        return "### What happened\nIt rose."

    monkeypatch.setattr(index_move.yf, "Ticker", _FakeTicker)
    from backend.components.analyst import news as news_module
    monkeypatch.setattr(news_module, "fetch_google_news", news)
    monkeypatch.setattr(market_data, "fetch_ticker_data", peers)
    monkeypatch.setattr(market_data, "get_trending_stocks", trending)
    monkeypatch.setattr(index_move.llm_service, "get_completion", completion)
    return calls


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1")
    return TestClient(app)


def test_the_model_is_given_the_session_peers_movers_and_fresh_headlines(world, client):
    body = client.get("/api/v1/market/index/%5ENSEI/analysis").json()

    assert body["analysis"].startswith("### What happened")
    assert body["session"]["close"] == 119.0
    assert body["session"]["change"] == pytest.approx(1.0)
    assert body["session"]["gap_percent"] == pytest.approx((120 - 118) / 118 * 100)
    # Duplicates (case-insensitive) and anything older than two days are dropped.
    assert [h["title"] for h in body["headlines"]] == ["RBI holds rates"]

    system, prompt = world["llm"][0]
    assert "never forecast or advise" in system
    assert "Close 119.00, previous close 118.00: +1.00 (+0.85%)" in prompt
    assert "SENSEX: +0.80%" in prompt
    assert "S&P 500: +0.80%" in prompt
    assert "NIFTY 50: +0.80%" not in prompt  # not its own peer
    assert "HDFCBANK: +2.50%" in prompt
    assert "RBI holds rates" in prompt and "Old story" not in prompt
    assert all(region == "IN" for _, region in world["news"])


def test_global_indices_skip_nifty_movers(world, client):
    client.get("/api/v1/market/index/%5EGSPC/analysis")
    _, prompt = world["llm"][0]
    assert "No mover data." in prompt
    assert world["news"] == [("S&P 500 stocks today", "US")]


def test_a_second_tap_is_served_from_cache(world, client):
    first = client.get("/api/v1/market/index/%5ENSEI/analysis").json()
    second = client.get("/api/v1/market/index/%5ENSEI/analysis").json()
    assert len(world["llm"]) == 1
    assert first["cached"] is False and second["cached"] is True


@pytest.mark.parametrize("reply", ["LLM_DISABLED", "Error generating response: boom", ""])
def test_an_unavailable_model_is_a_503_not_error_text(world, client, monkeypatch, reply):
    async def broken(prompt, system_prompt):
        return reply
    monkeypatch.setattr(index_move.llm_service, "get_completion", broken)

    resp = client.get("/api/v1/market/index/%5ENSEI/analysis")
    assert resp.status_code == 503
    assert index_move._cache == {}  # a failure is never cached


def test_an_unlisted_ticker_is_refused(world, client):
    assert client.get("/api/v1/market/index/AAPL/analysis").status_code == 404
    assert world["llm"] == []
