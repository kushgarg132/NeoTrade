from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.components.shared.models import PriceCandle
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.plan import replay
from backend.plan.store import COLLECTION

IST = timezone(timedelta(hours=5, minutes=30))
DAY = date(2026, 10, 6)
OPEN = datetime(2026, 10, 6, 9, 15, tzinfo=IST)


class _Provider:
    """An ORB breakout on a volume spike, then a fall through its stop."""

    def __init__(self, empty=False):
        rows = [(100, 101, 99, 100), (100, 102, 100, 101), (101, 101, 98, 99)] + [(100, 101, 99, 100)] * 10
        rows += [(100, 105.5, 100, 105), (105, 105, 90, 91), (91, 92, 90, 91)]
        vols = [1000.0] * 13 + [5000.0, 1000.0, 1000.0]
        self._candles = [] if empty else [
            PriceCandle(symbol="TCS", timestamp=OPEN + i * timedelta(minutes=5), open=o, high=h, low=l, close=c,
                        volume=vols[i]) for i, (o, h, l, c) in enumerate(rows)]

    async def history(self, instrument, interval, period):
        return self._candles

    async def quote(self, instrument):
        return {}


@pytest.fixture
def mongo(monkeypatch):
    async def get(self, exchange, symbol):
        return Instrument(instrument_token=1, exchange_token=1, exchange="NSE", tradingsymbol=symbol, name=symbol,
                          instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)
    monkeypatch.setattr(InstrumentMaster, "get", get)
    return AsyncMongoMockClient()["test_db"]


async def _ran_today(db, plan_allow):
    await db["trading_runs"].insert_one({"run_id": "r1", "user_id": "alice", "mode": "INTRADAY", "universe": ["TCS"],
                                 "params": {}, "started_at": OPEN.astimezone(timezone.utc)})
    await db[COLLECTION].insert_one({"user_id": "alice", "date": DAY.isoformat(), "version": 1,
                                     "at": (OPEN - timedelta(minutes=30)).astimezone(timezone.utc),
                                     "trigger": "pre_open", "skip_day": False, "risk_multiplier": 1.0,
                                     "max_positions": 10, "add_symbols": [], "allow": plan_allow, "exits": [],
                                     "rationale": []})


async def test_replay_scores_plan_and_baseline_on_the_same_bars(mongo):
    await _ran_today(mongo, [])
    doc = await replay.replay_day(mongo, _Provider(), "alice", DAY)
    assert doc["a"]["trades"] == 0 and doc["b"]["trades"] >= 1
    stored = await mongo["plan_scorecards"].find_one({"user_id": "alice", "date": DAY.isoformat()})
    assert stored["b"]["trades"] == doc["b"]["trades"]


async def test_replay_skips_users_without_a_run_or_bars(mongo):
    assert await replay.replay_day(mongo, _Provider(), "alice", DAY) is None
    await _ran_today(mongo, [])
    assert await replay.replay_day(mongo, _Provider(empty=True), "alice", DAY) is None
    assert await mongo["plan_scorecards"].count_documents({}) == 0


async def test_weeks_beating_counts_consecutive_weeks(mongo):
    def card(day, a, b):
        return {"user_id": "alice", "date": day.isoformat(), "a": {"net": a, "max_drawdown": 1.0},
                "b": {"net": b, "max_drawdown": 1.0}}
    mondays = [date(2026, 9, 7) + timedelta(weeks=i) for i in range(4)]
    await mongo["plan_scorecards"].insert_many([card(mondays[0], -5, 5)] + [card(d, 10, 1) for d in mondays[1:]])
    assert await replay.weeks_beating(mongo, "alice") == 3


async def test_baseline_trades_the_base_universe_and_the_plan_its_adds(mongo):
    await _ran_today(mongo, [])
    await mongo["trading_runs"].update_one({"run_id": "r1"}, {"$set": {
        "universe": ["TCS", "INFY", "RELIANCE"], "params": {"base_universe": ["TCS"], "plan_adds": ["INFY"]}}})
    provider = _Provider()
    seen = []
    original = provider.history

    async def history(instrument, interval, period):
        seen.append(instrument.tradingsymbol)
        return await original(instrument, interval, period)
    provider.history = history
    await replay.replay_day(mongo, provider, "alice", DAY)
    assert sorted(seen) == ["INFY", "TCS", "TCS"]  # A: base + adds; B: base only; never RELIANCE
