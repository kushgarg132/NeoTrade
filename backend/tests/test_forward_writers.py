from datetime import datetime, timezone
from unittest.mock import AsyncMock

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Intent, Order, Side
from backend.engine.portfolio import Portfolio
from backend.engine.runner import Proposal, size_intents
from backend.forward.store import ForwardStore, engine_recorder
from backend.scoring.composite import CompositeScore
from backend.suggestions.sink import SuggestionSink
from backend.suggestions.store import SuggestionStore
from backend.tests.test_forecast_picks import _fires_on_last_day, _frames
from backend.tests.test_size_intents import _FakeCtx, _FakeStrategy, _no_sentiment_redis


async def _records(db):
    return await db["forward_records"].find({}).to_list(length=None)


def _proposal(max_hold=None):
    return Proposal(
        order=Order(id="o1", symbol="TCS", side=Side.BUY, quantity=5.0, order_type="MARKET",
                    limit_price=None, product="CNC"),
        intent=Intent(symbol="TCS", side=Side.BUY, strength=0.7, reason_codes=["b"], stop_hint=90.0,
                      max_hold_days=max_hold),
        score=CompositeScore(rule_score=0.7, ai_score=0.0), entry=100.0, mode="LONGTERM")


async def test_picks_write_forward_records_and_survive_a_failing_store(monkeypatch):
    from backend.datalayer import bars
    from backend.forecast import picks, setups, study

    monkeypatch.setattr(setups, "SETUPS", (setups.Setup("fake", "Fake", 2, _fires_on_last_day, lambda t, s, d: "x"),))
    monkeypatch.setattr(study, "MIN_N", 1)
    frames = _frames(days=60, n=2)
    day = frames["S0"].index[55]
    now = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)

    async def seed(db):
        for symbol, df in frames.items():
            await bars.write(db, symbol, df.iloc[:56])

    db = AsyncMongoMockClient()["a"]
    await seed(db)
    await picks.run(db, now)
    recs = {r["name"]: r for r in await _records(db)}
    assert set(recs) == {"fake", "fake:long"}  # each pick plus its long-hold paper twin
    base, long = recs["fake"], recs["fake:long"]
    assert base["source"] == long["source"] == "picks" and base["user_id"] == "system"
    assert base["horizon_days"] == 2 and long["horizon_days"] == 4
    assert set(base["predicted"]) == {"p_up", "median"} and long["predicted"] is None

    async def boom(self, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(ForwardStore, "record", boom)
    db2 = AsyncMongoMockClient()["b"]
    await seed(db2)
    assert (await picks.run(db2, now))["picks"] == 1
    assert await db2["picks"].count_documents({}) == 1


async def test_sink_records_suggestion_and_news():
    db = AsyncMongoMockClient()["s"]
    await SuggestionSink(SuggestionStore(db), user_id="u", source="scan")(_proposal(max_hold=12))
    await SuggestionSink(SuggestionStore(db), user_id="v", source="news")(_proposal())
    by = {r["source"]: r for r in await _records(db)}
    assert by["suggestion"]["horizon_days"] == 12 and by["suggestion"]["name"] == "unknown"
    assert by["news"]["horizon_days"] == 5 and by["news"]["name"] == "news"
    sink = SuggestionSink(SuggestionStore(db), user_id="u", source="scan")
    await sink(_proposal())  # pending exists for u/TCS
    sink.armed = False
    await sink(_proposal())
    assert len(await _records(db)) == 2


async def test_suggestion_default_horizon_20():
    db = AsyncMongoMockClient()["s"]
    await SuggestionSink(SuggestionStore(db), user_id="u", source="scan")(_proposal())
    assert (await _records(db))[0]["horizon_days"] == 20


async def _size(mode, forward):
    intent = Intent(symbol="RELIANCE", side=Side.BUY, strength=0.9, reason_codes=["s"], stop_hint=90.0)
    return await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {"RELIANCE": _FakeStrategy(mode, "orb")},
        _no_sentiment_redis(), account_size=1_000_000.0, max_exposure=1_000_000.0, forward=forward)


async def test_runner_hook_records_intraday_entries_only():
    db = AsyncMongoMockClient()["r"]
    assert len(await _size("INTRADAY", engine_recorder(db, "u"))) == 1
    recs = await _records(db)
    assert len(recs) == 1 and recs[0]["source"] == "engine" and recs[0]["name"] == "orb"
    assert recs[0]["intraday"] and recs[0]["horizon_days"] == 0 and recs[0]["ref_price"] == 100.0

    db2 = AsyncMongoMockClient()["r2"]
    await _size("LONGTERM", engine_recorder(db2, "u"))
    await _size("INTRADAY", None)
    assert await _records(db2) == []


async def test_runner_hook_failure_does_not_change_the_order():
    assert len(await _size("INTRADAY", AsyncMock(side_effect=RuntimeError("x")))) == 1


async def test_engine_recorder_stores_nifty_ref_best_effort():
    class R:
        async def get(self, key):
            assert key == "macro:^NSEI"
            return '{"value": 24500.5}'

    db = AsyncMongoMockClient()["n"]
    order = Order(id="o", symbol="TCS", side=Side.BUY, quantity=1.0, order_type="MARKET", limit_price=None,
                  product="MIS", strategy_name="orb")
    now = datetime(2026, 10, 19, 5, tzinfo=timezone.utc)
    await engine_recorder(db, "u", R())(order, None, 100.0, now)
    assert (await _records(db))[0]["nifty_ref"] == 24500.5
    db2 = AsyncMongoMockClient()["n2"]
    await engine_recorder(db2, "u")(order, None, 100.0, now)
    assert (await _records(db2))[0]["nifty_ref"] is None
