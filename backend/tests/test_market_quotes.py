"""GET /market/quotes: prices for the search suggestions, one batched
download per symbol set, cached."""

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import market_cache
from backend.routers import market_data


def _closes(*values):
    index = pd.bdate_range(end="2026-10-02", periods=len(values))
    return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values, "Volume": 1.0}, index=index)


@pytest.fixture
def client(monkeypatch):
    market_cache._local.clear()
    market_data._quote_cache.clear()
    monkeypatch.setattr(market_cache, "_redis", lambda: None)
    app = FastAPI()
    app.include_router(market_data.router)
    calls = []

    def use(frame):
        def download(*args, **kwargs):
            calls.append(args)
            return frame
        monkeypatch.setattr(market_data.yf, "download", download)

    return TestClient(app), use, calls


def test_quotes_from_last_two_closes_in_request_order(client):
    http, use, _ = client
    use(pd.concat({"ITC.NS": _closes(400.0, 410.0), "INFY.NS": _closes(1500.0, 1485.0)}, axis=1))
    body = [{k: v for k, v in q.items() if k != "at"} for q in http.get("/market/quotes", params={"symbols": "infy,ITC"}).json()]
    assert body == [
        {"symbol": "INFY", "price": 1485.0, "change_pct": -1.0},
        {"symbol": "ITC", "price": 410.0, "change_pct": 2.5},
    ]


def test_single_symbol_flat_columns(client):
    http, use, _ = client
    use(_closes(100.0, 101.0))
    (q,) = http.get("/market/quotes", params={"symbols": "ITC"}).json()
    assert q.pop("at") > 0 and q == {"symbol": "ITC", "price": 101.0, "change_pct": 1.0}


def test_symbol_without_data_is_omitted(client):
    http, use, _ = client
    use(pd.concat({"ITC.NS": _closes(400.0, 410.0), "GONE.NS": _closes(1.0, 1.0) * np.nan}, axis=1))
    assert [q["symbol"] for q in http.get("/market/quotes", params={"symbols": "ITC,GONE"}).json()] == ["ITC"]


def test_nothing_at_all_is_empty_list(client):
    http, use, _ = client
    use(pd.DataFrame())
    assert http.get("/market/quotes", params={"symbols": "ITC,INFY"}).json() == []


@pytest.mark.parametrize("symbols", [",".join(f"S{i}" for i in range(9)), "", " , "])
def test_more_than_eight_or_none_is_422(client, symbols):
    http, _, _ = client
    assert http.get("/market/quotes", params={"symbols": symbols}).status_code == 422


def test_identical_request_is_cached(client):
    http, use, calls = client
    use(_closes(100.0, 101.0))
    http.get("/market/quotes", params={"symbols": "ITC"})
    http.get("/market/quotes", params={"symbols": "itc"})
    assert len(calls) == 1


def test_cached_set_still_follows_each_requests_order(client):
    http, use, _ = client
    use(pd.concat({"ITC.NS": _closes(400.0, 410.0), "INFY.NS": _closes(1500.0, 1485.0)}, axis=1))
    first = [q["symbol"] for q in http.get("/market/quotes", params={"symbols": "ITC,INFY"}).json()]
    second = [q["symbol"] for q in http.get("/market/quotes", params={"symbols": "INFY,ITC"}).json()]
    assert (first, second) == (["ITC", "INFY"], ["INFY", "ITC"])


def test_quotes_older_than_the_ttl_are_fetched_again(client, monkeypatch):
    """Typeahead sets rarely repeat within a minute: an old set must not come
    back with days-old prices."""
    http, use, calls = client
    use(_closes(100.0, 101.0))
    clock = {"t": 1000.0}
    monkeypatch.setattr(market_data.time, "monotonic", lambda: clock["t"])
    http.get("/market/quotes", params={"symbols": "ITC"})
    clock["t"] += market_data.QUOTES_TTL + 1
    http.get("/market/quotes", params={"symbols": "ITC"})
    assert len(calls) == 2


async def test_index_rows_come_from_the_cache_and_only_missing_ones_are_fetched(monkeypatch):
    import json

    from backend.database import db

    class Redis:
        async def mget(self, keys):
            return [json.dumps({"symbol": "^NSEI", "value": 1.0, "change": 0.0, "percent": 0.0, "at": 5.0})
                    if k == "macro:^NSEI" else None for k in keys]

    fetched = []

    async def fetch(symbol, name):
        fetched.append(symbol)
        return {"name": name, "symbol": symbol, "value": 2.0, "change": 0.0, "percent": 0.0}

    monkeypatch.setattr(db, "redis", Redis())
    monkeypatch.setattr(market_data, "fetch_ticker_data", fetch)
    rows = await market_data._quotes({"NIFTY 50": "^NSEI", "SENSEX": "^BSESN"})
    assert fetched == ["^BSESN"]
    assert [(r["name"], r["at"]) for r in rows][0] == ("NIFTY 50", 5.0)
    assert rows[1]["name"] == "SENSEX" and rows[1]["at"] > 5.0


def test_quotes_come_from_the_ingest_cache_first(client, monkeypatch):
    import json

    from backend.database import db

    http, use, calls = client

    class Redis:
        async def mget(self, keys):
            return [json.dumps({"ltp": 110.0, "prev_close": 100.0, "at": 7.0}) if k == "quote:TCS" else None for k in keys]

    monkeypatch.setattr(db, "redis", Redis())
    use(_closes(50.0, 55.0))
    rows = http.get("/market/quotes", params={"symbols": "TCS,INFY"}).json()
    assert rows[0] == {"symbol": "TCS", "price": 110.0, "prev_close": 100.0, "change_pct": 10.0, "at": 7.0}
    assert rows[1]["symbol"] == "INFY" and rows[1]["price"] == 55.0 and rows[1]["at"] > 7.0
    assert len(calls) == 1 and calls[0][0] == ["INFY.NS"]  # only the miss went to Yahoo
