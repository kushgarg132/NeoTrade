"""A tap on an index opens /market/index/{ticker}: a year of closes and the
figures read off an index. Only indices the app already lists are served."""

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import market_data


class _FakeTicker:
    def __init__(self, closes):
        index = pd.date_range("2025-01-01", periods=len(closes), freq="D")
        self._hist = pd.DataFrame({"Close": closes}, index=index)

    def history(self, period, interval):
        return self._hist


@pytest.fixture
def client(monkeypatch):
    closes = [100.0 + i for i in range(250)]  # 100 .. 349, rising
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _FakeTicker(closes))
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1")
    return TestClient(app)


def test_a_listed_index_returns_its_figures(client):
    body = client.get("/api/v1/market/index/%5ENSEI").json()

    assert body["name"] == "NIFTY 50"
    assert body["value"] == 349.0
    assert body["change"] == pytest.approx(1.0)
    assert body["percent"] == pytest.approx(100 / 348)
    assert body["high_52w"] == 349.0
    assert body["low_52w"] == 100.0
    assert body["sma_50"] == pytest.approx(sum(range(300, 350)) / 50)
    assert body["sma_200"] == pytest.approx(sum(range(150, 350)) / 200)
    assert len(body["points"]) == 250
    assert body["points"][0] == {"date": "2025-01-01", "close": 100.0}


def test_global_indices_are_listed_too(client):
    assert client.get("/api/v1/market/index/%5EGSPC").json()["name"] == "S&P 500"


def test_an_unlisted_ticker_is_refused(client):
    assert client.get("/api/v1/market/index/AAPL").status_code == 404


def test_no_data_is_a_502_not_a_crash(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _FakeTicker([]))
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/market/index/%5ENSEI").status_code == 502


def test_the_52_week_range_is_the_last_year_of_five(monkeypatch):
    """Five years of closes feed the chart; the 52-week high and low read only the last 252 sessions."""
    closes = [1000.0] + [100.0 + i for i in range(1, 1260)]  # an old peak, then a slow rise
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _FakeTicker(closes))
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1")
    body = TestClient(app).get("/api/v1/market/index/%5EBSESN").json()
    assert len(body["points"]) == 1260
    assert body["high_52w"] == closes[-1] and body["low_52w"] == closes[-252]
