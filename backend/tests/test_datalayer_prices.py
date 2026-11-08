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


async def test_quotes_cover_picks_still_open(mongo, monkeypatch):
    await mongo["picks"].insert_many([{"symbol": "DELTACORP", "due_date": "2999-01-01"},
                                      {"symbol": "GONE", "due_date": "2000-01-01"}])
    asked = []
    monkeypatch.setattr(prices, "last_two", lambda tickers: asked.append(set(tickers)) or {t: (1.0, 1.0) for t in tickers})
    monkeypatch.setattr(prices, "in_session", lambda now: False)
    monkeypatch.setattr("backend.factor.data.universe", lambda: ["RELIANCE"])
    monkeypatch.setattr(prices, "_last_universe", 0.0)

    await prices.quotes(mongo, FakeRedis())
    assert asked == [{"RELIANCE.NS", "DELTACORP.NS"}]


async def test_macro_writes_cache_and_daily_series(mongo, monkeypatch):
    monkeypatch.setattr(prices, "last_two", lambda tickers: {"BZ=F": (88.0, 80.0)})
    redis = FakeRedis()
    await prices.macro(mongo, redis)
    row = json.loads(redis.data["macro:BZ=F"])
    assert row["name"] == "Brent crude" and row["percent"] == pytest.approx(10.0)
    assert (await mongo["macro_series"].find_one())["value"] == 88.0

    rows = await prices.macro_rows(redis, {"Brent": "BZ=F", "Gold": "GC=F"})  # Gold missing: caller fetches only it
    assert rows == [{"name": "Brent", "symbol": "BZ=F", "value": 88.0, "change": 8.0,
                     "percent": pytest.approx(10.0), "at": pytest.approx(time.time(), abs=60)}]


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


def test_last_two_survives_an_empty_download(monkeypatch):
    monkeypatch.setattr(prices.yf, "download", lambda *a, **k: pd.DataFrame())
    assert prices.last_two(["A.NS"]) == {}


async def test_a_failed_universe_download_backs_off_until_the_next_cadence(mongo, monkeypatch):
    calls = []

    def boom(tickers):
        calls.append(1)
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(prices, "last_two", boom)
    monkeypatch.setattr(prices, "in_session", lambda now: True)
    monkeypatch.setattr("backend.factor.data.universe", lambda: ["RELIANCE"])
    monkeypatch.setattr(prices, "_last_universe", 0.0)
    with pytest.raises(RuntimeError):
        await prices.quotes(mongo, FakeRedis())
    await prices.quotes(mongo, FakeRedis())  # inside the cadence: no second download
    assert len(calls) == 1


async def test_a_price_only_write_keeps_the_previous_close():
    from backend.tests.test_datalayer_news import FakeRedis

    redis = FakeRedis()
    await marks.store_quotes(redis, {"TCS": (100.0, 99.0)}, 60)
    await marks.store_quotes(redis, {"TCS": (101.0, None), "NEW": (5.0, None)}, 60)
    assert json.loads(redis.data["quote:TCS"])["ltp"] == 101.0
    assert json.loads(redis.data["quote:TCS"])["prev_close"] == 99.0
    assert json.loads(redis.data["quote:NEW"])["prev_close"] is None
    await marks.store_quotes(redis, {"TCS": (102.0, 101.0)}, 60)
    assert json.loads(redis.data["quote:TCS"])["prev_close"] == 101.0  # a real close still wins


def _by_interval(monkeypatch, frames):
    monkeypatch.setattr(prices.yf, "download", lambda tickers, interval, **kw: frames[interval])


def test_last_two_reads_past_a_missing_daily_session(monkeypatch):
    _by_interval(monkeypatch, {
        "5m": pd.DataFrame({("Close", "^NSEI"): [23400.0, 23440.8], ("Close", "A.NS"): [1290.0, 1300.0], ("Close", "NOBARS.NS"): [None, None]},
                           index=pd.to_datetime(["2026-11-02 09:15", "2026-11-02 15:25"])),
        "1d": pd.DataFrame({("Close", "^NSEI"): [22936.8, 23053.1, None], ("Close", "A.NS"): [1167.4, 1164.9, None], ("Close", "NOBARS.NS"): [10.0, 11.0, None]},
                           index=pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-02"])),
    })
    assert prices.last_two(["^NSEI", "A.NS", "NOBARS.NS"]) == {"^NSEI": (23440.8, 23053.1), "A.NS": (1300.0, 1164.9), "NOBARS.NS": (11.0, 10.0)}


def test_last_two_uses_the_day_before_when_the_daily_bar_is_current(monkeypatch):
    _by_interval(monkeypatch, {
        "5m": pd.DataFrame({("Close", "^NSEI"): [23400.0]}, index=pd.to_datetime(["2026-11-02 15:25"])),
        "1d": pd.DataFrame({("Close", "^NSEI"): [23053.1, 23399.0]}, index=pd.to_datetime(["2026-10-30", "2026-11-02"])),
    })
    # A finished session's daily close is the official one; the last 5-minute trade is not.
    assert prices.last_two(["^NSEI"]) == {"^NSEI": (23399.0, 23053.1)}


def test_last_two_takes_the_previous_close_from_intraday_when_the_daily_bar_missed_it(monkeypatch):
    """2026-11-03: 45 of the Nifty 200 had no 2 Nov daily bar yet, so the day move was measured from 30 Oct."""
    _by_interval(monkeypatch, {
        "5m": pd.DataFrame({("Close", "INFY.NS"): [1161.0, 1136.7]},
                           index=pd.to_datetime(["2026-11-02 15:25", "2026-11-03 12:40"])),
        "1d": pd.DataFrame({("Close", "INFY.NS"): [1120.0, 1135.0, None]},
                           index=pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-03"])),
    })
    assert prices.last_two(["INFY.NS"]) == {"INFY.NS": (1136.7, 1161.0)}


def test_last_two_keeps_the_last_trade_while_the_session_runs(monkeypatch):
    monkeypatch.setattr(prices, "in_session", lambda now: True)
    today = prices.datetime.now(prices.IST).date().isoformat()
    _by_interval(monkeypatch, {
        "5m": pd.DataFrame({("Close", "A.NS"): [10.5]}, index=pd.to_datetime([f"{today} 12:40"])),
        "1d": pd.DataFrame({("Close", "A.NS"): [9.0, 10.2]}, index=pd.to_datetime(["2020-01-01", today])),
    })
    assert prices.last_two(["A.NS"]) == {"A.NS": (10.5, 9.0)}


def test_last_two_keeps_the_daily_figures_when_intraday_fails(monkeypatch):
    daily = pd.DataFrame({("Close", "A.NS"): [10.0, 11.0]}, index=pd.to_datetime(["2026-10-29", "2026-10-30"]))

    def download(tickers, interval, **kw):
        if interval == "5m":
            raise RuntimeError("no intraday")
        return daily
    monkeypatch.setattr(prices.yf, "download", download)
    assert prices.last_two(["A.NS"]) == {"A.NS": (11.0, 10.0)}


async def test_a_price_only_write_does_not_shorten_the_life_of_the_close():
    calls = []

    class Pipe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def set(self, key, value, **kw):
            calls.append((key, kw))

        async def execute(self):
            return []

    class Redis:
        async def mget(self, keys):
            return [json.dumps({"ltp": 1.0, "prev_close": 99.0, "at": 1}) if "TCS" in k else None for k in keys]

        def pipeline(self, transaction=False):
            return Pipe()

    await marks.store_quotes(Redis(), {"TCS": (100.0, None), "NEW": (5.0, None), "REAL": (7.0, 6.0)}, 60)
    assert dict(calls) == {"quote:TCS": {"keepttl": True}, "quote:NEW": {"ex": 60}, "quote:REAL": {"ex": 60}}


class _Feed:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.asked = rows or {}, error, []

    async def batch_quotes(self, symbols):
        self.asked.append(set(symbols))
        if self.error:
            raise self.error
        return {s: self.rows[s] for s in symbols if s in self.rows}


def _session(monkeypatch, adapter):
    async def session(db, redis):
        return ("upstox", adapter) if adapter else (None, None)

    monkeypatch.setattr("backend.datalayer.bars._broker_session", session)


@pytest.fixture
def universe_in_session(mongo, monkeypatch):
    asked = []
    monkeypatch.setattr(prices, "last_two", lambda tickers: asked.append(set(tickers)) or {t: (1.0, 1.0) for t in tickers})
    monkeypatch.setattr(prices, "in_session", lambda now: True)
    monkeypatch.setattr("backend.factor.data.universe", lambda: ["RELIANCE", "INFY"])
    monkeypatch.setattr(prices, "_last_universe", 0.0)
    return asked


async def test_a_broker_session_prices_the_whole_universe_every_pass(mongo, monkeypatch, universe_in_session):
    feed = _Feed({"RELIANCE": (2500.0, 2490.0), "INFY": (1500.0, 1490.0)})
    _session(monkeypatch, feed)
    redis = FakeRedis()
    await prices.quotes(mongo, redis)
    await prices.quotes(mongo, redis)
    assert feed.asked == [{"RELIANCE", "INFY"}, {"RELIANCE", "INFY"}] and universe_in_session == []
    stored = json.loads(redis.data["quote:INFY"])
    assert stored["ltp"] == 1500.0 and stored["prev_close"] == 1490.0


async def test_a_name_the_broker_did_not_price_falls_back_to_yahoo(mongo, monkeypatch, universe_in_session):
    _session(monkeypatch, _Feed({"RELIANCE": (2500.0, 2490.0)}))
    redis = FakeRedis()
    await prices.quotes(mongo, redis)
    assert universe_in_session == [{"INFY.NS"}]
    assert json.loads(redis.data["quote:RELIANCE"])["ltp"] == 2500.0 and json.loads(redis.data["quote:INFY"])["ltp"] == 1.0


async def test_a_broker_error_or_no_session_is_yahoo_as_before(mongo, monkeypatch, universe_in_session):
    _session(monkeypatch, _Feed(error=RuntimeError("401")))
    await prices.quotes(mongo, FakeRedis())
    assert universe_in_session == [{"RELIANCE.NS", "INFY.NS"}]
    monkeypatch.setattr(prices, "_last_universe", 0.0)
    _session(monkeypatch, None)
    await prices.quotes(mongo, FakeRedis())
    assert universe_in_session[1] == {"RELIANCE.NS", "INFY.NS"}


async def test_an_adapter_without_batch_quotes_is_yahoo_as_before(mongo, monkeypatch, universe_in_session):
    _session(monkeypatch, object())  # Kite and Angel One have no batch call yet
    await prices.quotes(mongo, FakeRedis())
    assert universe_in_session == [{"RELIANCE.NS", "INFY.NS"}]


async def test_outside_the_session_the_broker_is_not_asked(mongo, monkeypatch, universe_in_session):
    monkeypatch.setattr(prices, "in_session", lambda now: False)
    feed = _Feed({"RELIANCE": (2500.0, 2490.0)})
    _session(monkeypatch, feed)
    await prices.quotes(mongo, FakeRedis())
    assert feed.asked == [] and universe_in_session == [{"RELIANCE.NS", "INFY.NS"}]
