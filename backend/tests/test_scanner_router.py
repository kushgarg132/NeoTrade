"""GET /scanner and fetch_daily: the user's universe in, findings out, one
batched download that never assumes a MultiIndex."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.research import scanner
from backend.routers import scanner as scanner_router
from backend.tests.scanner_frames import breakout_frame

_USER = User(
    id="alice", google_sub="sub-1", email="alice@example.com", name="Alice",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)


@pytest.fixture
def make_client(monkeypatch):
    def _make(universe, frames=None, error=None, stored=None):
        calls = []

        async def fake_fetch(symbols):
            calls.append(symbols)
            if error:
                raise error
            return frames or {}

        async def store(universe):
            return dict(stored or {})

        monkeypatch.setattr(scanner_router, "fetch_daily", fake_fetch)
        monkeypatch.setattr(scanner_router, "_stored", store)
        app = FastAPI()
        app.include_router(scanner_router.router)
        app.dependency_overrides[get_current_user] = lambda: _USER
        app.dependency_overrides[scanner_router.get_universe] = lambda: universe
        return TestClient(app), calls

    return _make


def test_scan_returns_findings_and_skipped(make_client):
    client, _ = make_client(["AAA", "GONE"], {"AAA": breakout_frame()})
    body = client.get("/scanner").json()
    assert body["scanned"] == 2
    assert body["findings"][0]["setup"] == "breakout"
    assert "confidence" not in body["findings"][0]
    assert body["skipped"] == [{"symbol": "GONE", "reason": "no data"}]
    assert body["as_of"] == "2026-10-02" and "scan_time" in body


def test_empty_universe(make_client):
    client, calls = make_client([])
    body = client.get("/scanner").json()
    assert (body["scanned"], body["findings"], calls) == (0, [], [])


def test_download_failure_is_502(make_client):
    client, _ = make_client(["AAA"], error=RuntimeError("yahoo down"))
    response = client.get("/scanner")
    assert response.status_code == 502
    assert "data provider" in response.json()["detail"]


def test_store_hits_skip_the_download(make_client):
    client, calls = make_client(["AAA", "BBB"], {"BBB": breakout_frame()}, stored={"AAA": breakout_frame()})
    body = client.get("/scanner").json()
    assert calls == [["BBB"]]
    assert {f["symbol"] for f in body["findings"]} == {"AAA", "BBB"}


def test_failed_download_still_scans_what_the_store_had(make_client):
    client, _ = make_client(["AAA", "GONE"], error=RuntimeError("yahoo down"), stored={"AAA": breakout_frame()})
    response = client.get("/scanner")
    assert response.status_code == 200
    assert response.json()["skipped"] == [{"symbol": "GONE", "reason": "no data"}]


def _ohlcv(n=5):
    index = pd.bdate_range(end="2026-10-02", periods=n)
    values = np.arange(n, dtype=float) + 100
    return pd.DataFrame(
        {"Open": values, "High": values + 1, "Low": values - 1, "Close": values, "Volume": 1000.0},
        index=index,
    )


async def test_fetch_daily_single_symbol(monkeypatch):
    monkeypatch.setattr(scanner.yf, "download", lambda *a, **k: _ohlcv())
    frames = await scanner.fetch_daily(["ITC"])
    assert list(frames) == ["ITC"]
    assert {"open", "high", "low", "close", "volume"} <= set(frames["ITC"].columns)


async def test_fetch_daily_drops_empty_symbol(monkeypatch):
    good = _ohlcv()
    gone = good.copy() * np.nan
    combined = pd.concat({"ITC.NS": good, "GONE.NS": gone}, axis=1)
    monkeypatch.setattr(scanner.yf, "download", lambda *a, **k: combined)
    assert set(await scanner.fetch_daily(["ITC", "GONE"])) == {"ITC"}


async def test_fetch_daily_raises_when_every_symbol_comes_back_empty(monkeypatch):
    # yfinance 1.x swallows per-ticker errors (outage, rate limit) and returns
    # all-NaN columns -- a total outage must not read as "nothing set up".
    gone = _ohlcv() * np.nan
    combined = pd.concat({"ITC.NS": gone, "GONE.NS": gone}, axis=1)
    monkeypatch.setattr(scanner.yf, "download", lambda *a, **k: combined)
    with pytest.raises(RuntimeError):
        await scanner.fetch_daily(["ITC", "GONE"])
