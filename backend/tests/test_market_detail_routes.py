"""Drill-down reads: GET /market/sector/{name} and GET /news/item/{id}."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend import market_cache
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db as database
from backend.routers import market_data, news

ROWS = [{"symbol": "ONGC", "name": "ONGC", "sector": "Oil & Gas"}, {"symbol": "TCS", "name": "TCS", "sector": "IT"},
        {"symbol": "RIL", "name": "Reliance", "sector": "Oil & Gas"}]
QUOTES = {s: {"price": 100.0, "change_pct": c, "at": 1.0} for s, c in [("ONGC", 1.0), ("TCS", 3.0), ("RIL", -2.0)]}


def test_market_scan_returns_all_movers_sorted():
    scan = market_data.market_scan(ROWS, QUOTES, {})
    assert [m["symbol"] for m in scan["movers"]] == ["TCS", "ONGC", "RIL"]


def test_sector_members_filters_by_name():
    scan = market_data.market_scan(ROWS, QUOTES, {})
    assert [m["symbol"] for m in market_data.sector_members(scan, "Oil & Gas")] == ["ONGC", "RIL"]
    assert market_data.sector_members(scan, "Nope") == []


@pytest.fixture
def http(monkeypatch):
    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    monkeypatch.setattr(database, "redis", None)
    monkeypatch.setattr(market_cache, "_local", {})
    app = FastAPI()
    app.include_router(market_data.router)
    app.include_router(news.router)
    now = datetime.now(timezone.utc)
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.io", name="A",
                                                             created_at=now)
    return TestClient(app), mongo, monkeypatch


def _fake_scan(monkeypatch):
    async def fake(key, ttl, fn):
        return market_data.market_scan(ROWS, QUOTES, {})

    monkeypatch.setattr(market_data, "cached", fake)


def test_sector_route_unknown_is_404(http):
    client, _, mp = http
    _fake_scan(mp)
    r = client.get("/market/sector/Nope")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown sector"


def test_sector_route_members_and_news(http):
    client, mongo, mp = http
    _fake_scan(mp)
    now = datetime.now(timezone.utc)
    asyncio.run(mongo["news_items"].insert_many([
        {"_id": "a", "title": "a", "status": "SCORED", "published_at": now - timedelta(hours=2),
         "impacts": [{"type": "sector", "target": "Oil & Gas"}]},
        {"_id": "b", "title": "b", "status": "SCORED", "published_at": now - timedelta(hours=1),
         "impacts": [{"type": "sector", "target": "Oil & Gas"}]},
        {"_id": "c", "title": "c", "status": "SCORED", "published_at": now, "impacts": [{"type": "sector", "target": "IT"}]},
    ]))
    body = client.get("/market/sector/Oil & Gas").json()
    assert body["sector"] == "Oil & Gas" and body["n"] == 2 and body["sentiment"] is None
    assert [m["symbol"] for m in body["members"]] == ["ONGC", "RIL"]
    assert [i["id"] for i in body["news"]] == ["b", "a"]
    assert "+00:00" in body["news"][0]["published_at"]


def _seed_item(mongo):
    asyncio.run(mongo["news_items"].insert_one(
        {"_id": "n1", "title": "t", "status": "SCORED", "published_at": datetime(2026, 10, 1), "impacts": []}))


def test_news_item_with_outcomes(http):
    client, mongo, _ = http
    _seed_item(mongo)
    asyncio.run(mongo["news_outcomes"].insert_many([
        {"_id": "n1:symbol:TCS", "type": "symbol", "target": "TCS", "direction": 0.8, "impact": 0.5, "ret_1d": 0.01,
         "bench_1d": 0.0, "move_1d": 0.01, "secret": "x"},
        {"_id": "n1:sector:IT", "type": "sector", "target": "IT", "direction": 0.5, "impact": 0.3},
        {"_id": "n10:symbol:TCS", "type": "symbol", "target": "TCS"},
    ]))
    body = client.get("/news/item/n1").json()
    assert body["id"] == "n1" and body["published_at"].startswith("2026-10-01") and "+00:00" in body["published_at"]
    assert len(body["outcomes"]) == 2 and all("_id" not in o and "secret" not in o for o in body["outcomes"])


def test_unscored_news_item_has_empty_outcomes(http):
    client, mongo, _ = http
    _seed_item(mongo)
    r = client.get("/news/item/n1")
    assert r.status_code == 200 and r.json()["outcomes"] == []


def test_news_item_unknown_is_404(http):
    client, _, _ = http
    r = client.get("/news/item/zzz")
    assert r.status_code == 404 and r.json()["detail"] == "News item not found"


# --- index intraday + scan news flag ---------------------------------------

def test_index_intraday_returns_points_for_a_tracked_index(http):
    client, _, mp = http
    market_data._intraday_cache.clear()
    rows = [{"t": f"2026-10-27T09:{15 + i}:00+05:30", "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0 + i, "volume": 5.0} for i in range(3)]
    mp.setattr(market_data, "_fetch_index_intraday_sync", lambda t, days=1: rows)
    r = client.get("/market/index/^NSEI/intraday")
    assert r.status_code == 200 and len(r.json()) == 3
    assert set(r.json()[0]) == {"t", "open", "high", "low", "close", "volume"}


def test_index_intraday_days_5_has_its_own_cache_entry(http):
    client, _, mp = http
    market_data._intraday_cache.clear()
    calls = []
    mp.setattr(market_data, "_fetch_index_intraday_sync",
               lambda t, days=1: calls.append((t, days)) or [{"t": "x", "close": 1.0}])
    client.get("/market/index/^NSEI/intraday?days=1")
    client.get("/market/index/^NSEI/intraday?days=5")
    client.get("/market/index/^NSEI/intraday?days=5")
    assert calls == [("^NSEI", 1), ("^NSEI", 5)]


def test_index_intraday_bad_days_is_422(http):
    client, _, _ = http
    assert client.get("/market/index/^NSEI/intraday?days=2").status_code == 422


def test_index_intraday_404_for_an_untracked_ticker(http):
    client, _, _ = http
    assert client.get("/market/index/NOPE/intraday").status_code == 404


def test_index_intraday_502_when_no_points(http):
    client, _, mp = http
    market_data._intraday_cache.clear()
    mp.setattr(market_data, "_fetch_index_intraday_sync", lambda t, days=1: [])
    assert client.get("/market/index/^NSEI/intraday").status_code == 502


def test_index_intraday_empty_is_negative_cached(http):
    client, _, mp = http
    market_data._intraday_cache.clear()
    calls = []
    mp.setattr(market_data, "_fetch_index_intraday_sync", lambda t, days=1: calls.append(t) or [])
    assert client.get("/market/index/^NSEI/intraday").status_code == 502
    assert client.get("/market/index/^NSEI/intraday").status_code == 502
    assert len(calls) == 1


def _scan_http(http):
    client, mongo, mp = http
    rows = [{"symbol": "TCS", "name": "TCS", "sector": "IT"}, {"symbol": "INFY", "name": "Infosys", "sector": "IT"}]
    q = {"TCS": {"price": 1.0, "change_pct": 3.0, "at": 1.0}, "INFY": {"price": 1.0, "change_pct": -2.0, "at": 1.0}}

    async def fake(key, ttl, fn):
        return market_data.market_scan(rows, q, {})

    mp.setattr(market_data, "cached", fake)
    return client, mongo, mp


def test_scan_movers_flag_news_in_the_last_24h(http):
    client, mongo, mp = _scan_http(http)
    asyncio.run(mongo["news_items"].insert_one(
        {"_id": "a", "status": "SCORED", "published_at": datetime.now(timezone.utc) - timedelta(hours=2),
         "impacts": [{"type": "symbol", "target": "TCS"}]}))
    body = client.get("/market/scan").json()
    assert body["gainers"][0]["symbol"] == "TCS" and body["gainers"][0]["news"] is True
    assert body["losers"][0]["symbol"] == "INFY" and body["losers"][0]["news"] is False


def test_scan_movers_news_false_when_the_news_query_fails(http):
    client, mongo, mp = _scan_http(http)

    class Boom:
        def __getitem__(self, k):
            raise RuntimeError("down")

    import types
    import backend.database as dbmod
    mp.setattr(dbmod, "db", types.SimpleNamespace(db=Boom(), redis=None))
    body = client.get("/market/scan").json()
    assert body["gainers"][0]["news"] is False and body["losers"][0]["news"] is False


def test_scan_response_has_no_movers_key(http):
    client, _, _ = _scan_http(http)
    assert "movers" not in client.get("/market/scan").json()
