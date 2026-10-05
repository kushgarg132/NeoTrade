import json
import time

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import marks
from backend.datalayer import prices


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, **_):
        self.data[key] = value
        return True

    async def mget(self, keys):
        return [self.data.get(k) for k in keys]

    def pipeline(self, transaction=False):
        redis = self

        class _Pipe:
            async def __aenter__(self):
                self.ops = []
                return self

            async def __aexit__(self, *exc):
                return False

            def set(self, *args, **kw):
                self.ops.append((args, kw))

            async def execute(self):
                for args, kw in self.ops:
                    await redis.set(*args, **kw)

        return _Pipe()


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def _frame(columns: dict) -> pd.DataFrame:
    return pd.concat({"Close": pd.DataFrame(columns)}, axis=1)


def test_last_two_reads_last_and_previous_close(monkeypatch):
    monkeypatch.setattr(prices.yf, "download", lambda *a, **k: _frame(
        {"A.NS": [10.0, 11.0], "B.NS": [float("nan"), 5.0], "C.NS": [float("nan")] * 2}))
    assert prices.last_two(["A.NS", "B.NS", "C.NS", "D.NS"]) == {"A.NS": (11.0, 10.0), "B.NS": (5.0, 5.0)}


async def test_quotes_refresh_priority_each_pass_and_universe_on_cadence(mongo, monkeypatch):
    await mongo["paper_positions"].insert_many([
        {"user_id": "u", "symbol": "TCS", "quantity": 5}, {"user_id": "u", "symbol": "OLD", "quantity": 0}])
    await mongo["watchlist"].insert_one({"user_id": "u", "symbols": ["INFY.NS"]})
    asked = []
    monkeypatch.setattr(prices, "last_two", lambda tickers: asked.append(set(tickers)) or {t: (1.0, 1.0) for t in tickers})
    monkeypatch.setattr(prices, "in_session", lambda now: True)
    monkeypatch.setattr("backend.factor.data.universe", lambda: ["RELIANCE"])
    monkeypatch.setattr(prices, "_last_universe", 0.0)
    redis = FakeRedis()

    await prices.quotes(mongo, redis)
    await prices.quotes(mongo, redis)
    assert asked == [{"TCS.NS", "INFY.NS", "RELIANCE.NS"}, {"TCS.NS", "INFY.NS"}]
    assert json.loads(redis.data["quote:INFY"])["ltp"] == 1.0


async def test_macro_writes_cache_and_daily_series(mongo, monkeypatch):
    monkeypatch.setattr(prices, "last_two", lambda tickers: {"BZ=F": (88.0, 80.0)})
    redis = FakeRedis()
    await prices.macro(mongo, redis)
    row = json.loads(redis.data["macro:BZ=F"])
    assert row["name"] == "Brent crude" and row["percent"] == pytest.approx(10.0)
    assert (await mongo["macro_series"].find_one())["value"] == 88.0

    assert await prices.macro_rows(redis, {"Brent": "BZ=F", "Gold": "GC=F"}) is None  # one missing: caller fetches
    assert await prices.macro_rows(redis, {"Brent": "BZ=F"}) == [
        {"name": "Brent", "symbol": "BZ=F", "value": 88.0, "change": 8.0, "percent": pytest.approx(10.0)}]


async def test_mark_prices_uses_fresh_cache_and_writes_through(mongo, monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(marks, "_redis", lambda: redis)
    await marks.store_quotes(redis, {"TCS": (100.0, 99.0)}, 60)
    redis.data["quote:OLD"] = json.dumps({"ltp": 5.0, "prev_close": None, "at": time.time() - 30})
    fetched = []

    class _Master:
        def __init__(self, _db):
            pass

        async def get(self, exchange, symbol):
            return symbol

    class _Provider:
        async def quote(self, instrument):
            fetched.append(instrument)
            return {"last_price": 7.0}

    monkeypatch.setattr(marks, "InstrumentMaster", _Master)
    monkeypatch.setattr(marks, "YFinanceProvider", _Provider)

    assert await marks.mark_prices(mongo, ["TCS", "OLD"]) == {"TCS": 100.0, "OLD": 5.0}
    assert fetched == []
    # An order path refuses the 30s-old cached price and fetches live.
    assert await marks.mark_prices(mongo, ["OLD"], max_age_seconds=marks.ORDER_MAX_AGE_SECONDS) == {"OLD": 7.0}
    assert fetched == ["OLD"]
    assert json.loads(redis.data["quote:OLD"])["ltp"] == 7.0
