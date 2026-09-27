"""The home page's market feeds come from a stale-while-revalidate cache:
only the first request after an empty cache waits on the source."""

import asyncio

import pytest

from backend import market_cache


@pytest.fixture(autouse=True)
def empty(monkeypatch):
    monkeypatch.setattr(market_cache, "_local", {})
    monkeypatch.setattr(market_cache, "_redis", lambda: None)


async def test_stale_values_are_served_at_once_and_refreshed_behind():
    calls = []

    async def fetch():
        calls.append(1)
        return [len(calls)]

    assert await market_cache.cached("k", 60, fetch) == [1]
    assert await market_cache.cached("k", 60, fetch) == [1] and len(calls) == 1  # fresh: no fetch

    market_cache._local["k"]["at"] -= 120  # now stale
    assert await market_cache.cached("k", 60, fetch) == [1]  # served stale immediately
    await asyncio.gather(*market_cache._tasks)
    assert await market_cache.cached("k", 60, fetch) == [2]  # the background refresh landed


async def test_an_empty_answer_is_not_cached():
    async def nothing():
        return []

    assert await market_cache.cached("k", 60, nothing) == []
    assert "k" not in market_cache._local


class _Redis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


async def test_redis_is_shared_and_only_one_worker_refreshes(monkeypatch):
    redis = _Redis()
    monkeypatch.setattr(market_cache, "_redis", lambda: redis)
    calls = []

    async def fetch():
        calls.append(1)
        return ["x"]

    await market_cache.cached("k", 60, fetch)
    market_cache._local.clear()  # another worker: nothing in its memory
    assert await market_cache.cached("k", 60, fetch) == ["x"] and len(calls) == 1

    import json
    entry = json.loads(redis.store["market:k"])
    entry["at"] -= 120
    redis.store["market:k"] = json.dumps(entry)
    await market_cache.cached("k", 60, fetch)
    await market_cache.cached("k", 60, fetch)  # second stale read: refresh already claimed
    await asyncio.gather(*market_cache._tasks)
    assert len(calls) == 2


def test_movers_come_from_one_batched_download(monkeypatch):
    import pandas as pd

    from backend.routers import market_data

    symbols = ["A.NS", "B.NS", "C.NS"]
    monkeypatch.setattr(market_data, "NIFTY_50_SYMBOLS", symbols)
    frame = pd.DataFrame({("Close", "A.NS"): [100.0, 101.0], ("Close", "B.NS"): [100.0, 90.0],
                          ("Close", "C.NS"): [100.0, None]})
    calls = []
    monkeypatch.setattr(market_data.yf, "download", lambda tickers, **kw: calls.append(tickers) or frame)

    movers = market_data._movers_sync()
    assert calls == [symbols]
    assert [(m["symbol"], round(m["percent"], 1)) for m in movers] == [("B.NS", -10.0), ("A.NS", 1.0)]
