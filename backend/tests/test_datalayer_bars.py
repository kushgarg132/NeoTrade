from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.data.providers.store import StoreFundamentals, StoreHistoryProvider
from backend.datalayer import bars
from backend.instruments.models import Instrument
from backend.screening.protocols import FundamentalSnapshot

TODAY = bars.today_ist()
AFTER_CLOSE = datetime.combine(TODAY, time(16, 30), bars.IST)


class FakeRedis:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, **_):
        self.data[key] = value


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def _frame(days: int, end: date = TODAY, start_close: float = 100.0) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=days)
    close = [start_close + i for i in range(days)]
    return pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
         "close": close, "volume": 1000.0},
        index=index,
    )


def _instrument(symbol="AAA", exchange="NSE"):
    return Instrument(instrument_token=1, exchange_token=1, exchange=exchange, tradingsymbol=symbol, name=symbol,
                      instrument_type="EQ", segment=exchange, lot_size=1, tick_size=0.05)


class Fallback:
    def __init__(self):
        self.calls = []

    async def history(self, instrument, interval, period):
        self.calls.append((instrument.tradingsymbol, interval, period))
        return ["fallback"]

    async def snapshot(self, instrument):
        self.calls.append(instrument.tradingsymbol)
        return "fallback"


@pytest.mark.parametrize("as_of,ist_time,due", [
    (None, (10, 0), True),  # never filled: fill now
    ("yesterday", (10, 0), False),  # before the close: yesterday's bars are the latest
    ("yesterday", (15, 50), True),
    ("today", (15, 50), False),
])
def test_due(as_of, ist_time, due):
    now = datetime.combine(TODAY, datetime.min.time().replace(hour=ist_time[0], minute=ist_time[1]), bars.IST)
    marks = {"yesterday": (TODAY - timedelta(days=1)).isoformat(), "today": TODAY.isoformat(), None: None}
    assert bars._due(marks[as_of], now) is due


async def test_write_is_idempotent_and_read_drops_stale(mongo):
    await bars.ensure_indexes(mongo)
    await bars.write(mongo, "AAA", _frame(10))
    await bars.write(mongo, "AAA", _frame(10, start_close=200))  # a re-download overwrites
    await bars.write(mongo, "OLD", _frame(10, end=TODAY - timedelta(days=10)))
    assert await mongo[bars.BARS].count_documents({"symbol": "AAA"}) == 10

    frames = await bars.read(mongo, ["AAA", "OLD", "NONE"], TODAY - timedelta(days=30))
    assert set(frames) == {"AAA"}
    assert frames["AAA"]["close"].iloc[0] == 200 and frames["AAA"].index.is_monotonic_increasing


async def test_loop_backfills_new_symbols_and_tops_up_known_ones(mongo, monkeypatch):
    await bars.write(mongo, "KNOWN", _frame(5))
    await bars.write(mongo, bars.NIFTY, _frame(5))
    downloads = []

    def fake_download(tickers, period):
        downloads.append((period, sorted(tickers)))
        return {t: _frame(3) for t in tickers}

    async def fake_symbols(db):
        return {"KNOWN", "NEW"}

    monkeypatch.setattr(bars, "_download", fake_download)
    monkeypatch.setattr(bars, "symbols", fake_symbols)
    redis = FakeRedis({bars.BARS_FULL_KEY: TODAY.isoformat()})
    await bars.loop(mongo, redis, now=AFTER_CLOSE)

    assert downloads == [("2y", ["NEW.NS"]), ("1mo", ["KNOWN.NS"]), ("1mo", [bars.NIFTY])]
    assert redis.data[bars.BARS_AS_OF_KEY] == TODAY.isoformat()
    assert set(await mongo[bars.BARS].distinct("symbol")) == {"KNOWN", "NEW", bars.NIFTY}


async def test_weekly_pass_redownloads_everything(mongo, monkeypatch):
    await bars.write(mongo, "KNOWN", _frame(5))
    downloads = []
    monkeypatch.setattr(bars, "_download", lambda t, p: downloads.append((p, sorted(t))) or {x: _frame(3) for x in t})

    async def fake_symbols(db):
        return {"KNOWN"}

    monkeypatch.setattr(bars, "symbols", fake_symbols)
    redis = FakeRedis({bars.BARS_FULL_KEY: (TODAY - timedelta(days=8)).isoformat()})
    await bars.loop(mongo, redis, now=AFTER_CLOSE)
    assert downloads == [("2y", ["KNOWN.NS"]), ("1mo", []), ("10y", [bars.NIFTY])]
    assert redis.data[bars.BARS_FULL_KEY] == TODAY.isoformat()


async def test_loop_with_no_data_does_not_mark_the_day_done(mongo, monkeypatch):
    monkeypatch.setattr(bars, "_download", lambda t, p: {})

    async def fake_symbols(db):
        return {"AAA"}

    monkeypatch.setattr(bars, "symbols", fake_symbols)
    redis = FakeRedis()
    with pytest.raises(RuntimeError):
        await bars.loop(mongo, redis)
    assert bars.BARS_AS_OF_KEY not in redis.data


async def test_store_history_serves_a_covered_daily_period(mongo):
    await bars.write(mongo, "AAA", _frame(300))
    fallback = Fallback()
    candles = await StoreHistoryProvider(mongo, fallback).history(_instrument(), "1d", "1y")
    assert fallback.calls == []
    assert candles[-1].timestamp.date() == pd.bdate_range(end=TODAY, periods=1)[0].date()
    assert candles[-1].symbol == "AAA.NS" and candles[0].timestamp.tzinfo is not None


@pytest.mark.parametrize("interval,period,exchange", [
    ("5m", "5d", "NSE"),  # intraday
    ("1d", "5y", "NSE"),  # further back than stored
    ("1d", "max", "NSE"),
    ("1d", "1y", "BSE"),
])
async def test_store_history_falls_back(mongo, interval, period, exchange):
    await bars.write(mongo, "AAA", _frame(300))
    fallback = Fallback()
    assert await StoreHistoryProvider(mongo, fallback).history(_instrument(exchange=exchange), interval, period) == ["fallback"]


async def test_store_history_falls_back_when_the_store_is_short(mongo):
    await bars.write(mongo, "AAA", _frame(20))  # listed a month ago, or never backfilled
    fallback = Fallback()
    assert await StoreHistoryProvider(mongo, fallback).history(_instrument(), "1d", "1y") == ["fallback"]


async def test_store_fundamentals_fresh_and_stale(mongo):
    snap = FundamentalSnapshot(symbol="AAA", pe_ratio=20.0)
    now = datetime.now(timezone.utc)
    await mongo[bars.FUNDAMENTALS].insert_one({"_id": "AAA", **snap.model_dump(), "as_of": now})
    await mongo[bars.FUNDAMENTALS].insert_one({"_id": "OLD", **snap.model_dump(), "as_of": now - timedelta(days=5)})
    fallback = Fallback()
    store = StoreFundamentals(mongo, fallback)
    assert await store.snapshot(_instrument("AAA")) == snap
    assert await store.snapshot(_instrument("OLD")) == "fallback"
    assert fallback.calls == ["OLD"]


async def test_prev_closes_returns_each_symbols_last_close_before_the_day():
    from mongomock_motor import AsyncMongoMockClient

    db = AsyncMongoMockClient()["prev_closes"]
    await db[bars.BARS].insert_many([
        {"symbol": "TCS", "date": "2026-10-02", "close": 3000.0},
        {"symbol": "TCS", "date": "2026-10-05", "close": 3050.0},
        {"symbol": "TCS", "date": "2026-10-06", "close": 3100.0},
        {"symbol": "INFY", "date": "2026-10-03", "close": 1500.0},
    ])
    assert await bars.prev_closes(db, ["TCS", "INFY", "NONE"], date(2026, 10, 6)) == {"TCS": 3050.0, "INFY": 1500.0}
