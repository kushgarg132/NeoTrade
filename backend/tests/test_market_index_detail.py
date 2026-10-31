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
        self._hist = pd.DataFrame({"Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
                                   "Close": closes, "Volume": [1000.0] * len(closes)}, index=index)

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
    assert body["points"][0] == {"date": "2025-01-01", "open": 100.0, "high": 101.0, "low": 99.0,
                                 "close": 100.0, "volume": 1000.0}


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


def test_nan_rows_are_dropped_so_the_body_stays_valid_json(monkeypatch):
    """yfinance leaves NaN on half sessions; NaN is not JSON and would break the browser's parse."""
    closes = [100.0, float("nan"), 102.0]
    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _FakeTicker(closes))
    app = FastAPI()
    app.include_router(market_data.router, prefix="/api/v1")
    r = TestClient(app).get("/api/v1/market/index/%5ENSEI")
    assert "NaN" not in r.text
    assert [p["close"] for p in r.json()["points"]] == [100.0, 102.0]


def test_index_intraday_rows_carry_ohlcv_and_days_picks_the_window(monkeypatch):
    seen = []

    class _T(_FakeTicker):
        def history(self, period, interval):
            seen.append((period, interval))
            return self._hist

    monkeypatch.setattr(market_data.yf, "Ticker", lambda ticker: _T([100.0, 101.0]))
    rows = market_data._fetch_index_intraday_sync("^NSEI", 5)
    assert seen == [("5d", "15m")]
    assert set(rows[0]) == {"t", "open", "high", "low", "close", "volume"}
    market_data._fetch_index_intraday_sync("^NSEI")
    assert seen[-1] == ("1d", "5m")
