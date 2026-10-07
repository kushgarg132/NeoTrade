"""Scanning a universe for fresh long-term suggestions.

The strategies need months of history before they will say anything, but only
the newest bar's signals are actionable -- a breakout from six weeks ago is
not a trade you can still take. The scan therefore replays history to warm
the strategies up and only records suggestions from the final session.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Intent, Order, Side
from backend.engine.runner import Proposal
from backend.instruments.models import Instrument
from backend.scoring.composite import CompositeScore
from backend.suggestions.scan import scan_universe
from backend.suggestions.sink import SuggestionSink
from backend.suggestions.store import SuggestionStore

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


def _proposal(symbol="RELIANCE", mode="LONGTERM") -> Proposal:
    return Proposal(
        order=Order(id="o1", symbol=symbol, side=Side.BUY, quantity=5.0,
                    order_type="MARKET", limit_price=None, product="CNC"),
        intent=Intent(symbol=symbol, side=Side.BUY, strength=0.7,
                      reason_codes=["breakout"], stop_hint=90.0, target_hint=120.0),
        score=CompositeScore(rule_score=0.7, ai_score=0.0),
        entry=100.0,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# The sink's arming and de-duplication, which is what keeps a daily scan from
# filling the inbox with the same idea over and over.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_disarmed_sink_records_nothing(mongo):
    store = SuggestionStore(mongo)
    sink = SuggestionSink(store, user_id="alice", source="scan")
    sink.armed = False

    executed = await sink(_proposal())

    assert executed is False, "warmup signals must not execute either"
    assert await store.list("alice") == []


@pytest.mark.asyncio
async def test_sink_skips_a_symbol_that_already_has_a_pending_suggestion(mongo):
    store = SuggestionStore(mongo)
    sink = SuggestionSink(store, user_id="alice", source="scan")

    await sink(_proposal())
    await sink(_proposal())

    assert len(await store.list("alice", status="PENDING")) == 1


@pytest.mark.asyncio
async def test_a_decided_symbol_can_be_suggested_again(mongo):
    store = SuggestionStore(mongo)
    sink = SuggestionSink(store, user_id="alice", source="scan")
    await sink(_proposal())
    pending = (await store.list("alice"))[0]
    await store.decide("alice", pending["id"], status="REJECTED")

    await sink(_proposal())

    assert len(await store.list("alice", status="PENDING")) == 1


# ---------------------------------------------------------------------------
# The scan itself, against a fake provider (no yfinance in a unit test)
# ---------------------------------------------------------------------------

DAYS = 60
FINAL_CLOSE = 100.0 * (1.004 ** DAYS)


class _RisingHistoryProvider:
    """A clean uptrend ending today.

    The scan only looks back a bounded window, so a fixture anchored to a
    fixed past date would be filtered out entirely and every assertion below
    would pass by seeing nothing at all.
    """

    async def history(self, instrument, interval, period):
        from backend.components.shared.models import PriceCandle

        first_day = datetime.now(timezone.utc) - timedelta(days=DAYS)
        candles = []
        price = 100.0
        for day in range(DAYS):
            price *= 1.004
            candles.append(PriceCandle(
                symbol=instrument.tradingsymbol,
                timestamp=first_day + timedelta(days=day),
                open=price * 0.995, high=price * 1.02, low=price * 0.99,
                close=price, volume=100_000,
            ))
        return candles

    async def quote(self, instrument):
        raise NotImplementedError


class _AlwaysBuyStrategy:
    """Fires on every bar.

    The real strategies only speak on rare setups, so driving this test with
    them would mean asserting against silence -- which passes whether the
    arming logic works or the scan is broken. This one makes the arming
    itself the only thing that decides how many suggestions appear.
    """

    def __init__(self, universe, symbol_for_token):
        from backend.engine.protocols import StrategySpec

        self.symbol_for_token = symbol_for_token
        self.spec = StrategySpec(
            name="always_buy", mode="LONGTERM", timeframe="1d",
            warmup_bars=1, universe=universe,
        )

    def on_start(self, ctx) -> None:
        pass

    def on_fill(self, ctx, fill) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for_token.get(bar.instrument_token)
        if symbol is None:
            return
        ctx.submit(Intent(
            symbol=symbol, side=Side.BUY, strength=0.9, reason_codes=["always"],
            stop_hint=bar.close * 0.95, target_hint=bar.close * 1.1,
        ))


def _only_always_buy(universe, symbol_for_token, **_):
    return [_AlwaysBuyStrategy(universe, symbol_for_token)]


class _FakeMaster:
    def __init__(self, _db):
        pass

    async def get(self, exchange, tradingsymbol):
        return Instrument(
            exchange=exchange, tradingsymbol=tradingsymbol, name=tradingsymbol,
            instrument_token=abs(hash(tradingsymbol)) % 100000, exchange_token=1,
            instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
        )


@pytest.mark.asyncio
async def test_scan_records_one_suggestion_per_symbol_from_the_final_session(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _only_always_buy)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))

    created = await scan_universe(mongo, user_id="alice", universe=["RELIANCE", "TCS"])

    assert {s["symbol"] for s in created} == {"RELIANCE", "TCS"}
    assert all(s["source"] == "scan" and s["mode"] == "LONGTERM" for s in created)
    # The strategy fired on all 60 bars; only the last session's signal is
    # advice, so anything above one per symbol means the sink stayed armed
    # through the warmup replay.
    assert len(created) == 2
    assert created[0]["entry_ref"] == pytest.approx(FINAL_CLOSE, rel=1e-6)

    assert len(await SuggestionStore(mongo).list("alice", status="PENDING")) == 2


@pytest.mark.asyncio
async def test_scan_does_not_query_sentiment_for_warmup_bars(mongo, monkeypatch):
    """The sentiment cache only ever holds *today's* reading. Applying it to
    a signal that fired on one of the ~400 warmup days would misattribute
    today's mood to a stale day, and -- since `_AlwaysBuyStrategy` fires on
    every one of its 60 bars -- doing this for real would mean 60 Redis
    round trips for one symbol instead of the single one that's actually
    meaningful (the final, armed session).

    `scan_universe` also does one upfront, non-per-bar analyst-verdict cache
    read per scanned symbol before the bar replay even
    starts -- that's a fixed baseline unrelated to warmup, not a leak this
    test is about, so it's allowed for on top of the single per-bar read."""
    from unittest.mock import AsyncMock

    from backend.suggestions import scan as scan_module

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _only_always_buy)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))

    redis = AsyncMock()
    redis.get.return_value = "0.5"

    await scan_universe(mongo, user_id="alice", universe=["RELIANCE"], redis=redis)

    baseline = 1  # one upfront analyst-verdict read per scanned symbol
    assert redis.get.await_count <= baseline + 1, (
        "expected only the fixed analyst-verdict baseline plus at most one "
        f"sentiment lookup (the final session's), got {redis.get.await_count}"
    )


@pytest.mark.asyncio
async def test_scan_with_no_resolvable_symbols_returns_nothing(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    class _EmptyMaster(_FakeMaster):
        async def get(self, exchange, tradingsymbol):
            return None

    monkeypatch.setattr(scan_module, "InstrumentMaster", _EmptyMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())

    assert await scan_universe(mongo, user_id="alice", universe=["NOSUCH"]) == []


# ---------------------------------------------------------------------------
# Wiring the Task-2 analyst-verdict cache and Task-4 quality universe into
# the strategy-building call.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_wires_analyst_verdicts_into_strategy_build(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    captured = {}

    def _spy_build(universe, symbol_for_token, **kwargs):
        captured.update(kwargs)
        return [_AlwaysBuyStrategy(universe, symbol_for_token)]

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _spy_build)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))

    async def fake_get(key):
        if key == "analyst_verdict:RELIANCE":
            return json.dumps({
                "sentiment_score": 0.5, "impact_score": 7,
                "label": "bullish", "top_reason": "strong earnings",
            })
        return None  # every other key (e.g. sentiment:RELIANCE) -- no cached value

    redis = AsyncMock()
    redis.get.side_effect = fake_get

    await scan_universe(mongo, user_id="alice", universe=["RELIANCE"], redis=redis)

    assert captured["analyst_verdicts"]["RELIANCE"]["label"] == "bullish"


@pytest.mark.asyncio
async def test_scan_omits_symbols_with_no_cached_verdict(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    captured = {}

    def _spy_build(universe, symbol_for_token, **kwargs):
        captured.update(kwargs)
        return [_AlwaysBuyStrategy(universe, symbol_for_token)]

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _spy_build)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))

    redis = AsyncMock()
    redis.get.return_value = None  # nothing cached for any symbol

    await scan_universe(mongo, user_id="alice", universe=["RELIANCE"], redis=redis)

    # build_default_strategies documents None (not {}) as "don't include this
    # strategy" -- scan_universe now honors that contract when the cache came
    # back empty rather than passing a dead-but-truthy {} through.
    assert captured["analyst_verdicts"] is None


@pytest.mark.asyncio
async def test_scan_skips_analyst_verdict_fetch_without_redis(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    captured = {}

    def _spy_build(universe, symbol_for_token, **kwargs):
        captured.update(kwargs)
        return [_AlwaysBuyStrategy(universe, symbol_for_token)]

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _spy_build)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))

    await scan_universe(mongo, user_id="alice", universe=["RELIANCE"], redis=None)

    assert captured["analyst_verdicts"] is None


@pytest.mark.asyncio
async def test_scan_wires_quality_universe_into_strategy_build(mongo, monkeypatch):
    from backend.suggestions import scan as scan_module

    captured = {}

    def _spy_build(universe, symbol_for_token, **kwargs):
        captured.update(kwargs)
        return [_AlwaysBuyStrategy(universe, symbol_for_token)]

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _RisingHistoryProvider())
    monkeypatch.setattr(scan_module, "build_default_strategies", _spy_build)
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={"RELIANCE": 0.8}))

    await scan_universe(mongo, user_id="alice", universe=["RELIANCE"])

    assert captured["quality_scores"] == {"RELIANCE": 0.8}
    assert captured["quality_universe"] == ["RELIANCE"]


def _sell(symbol="RELIANCE", quantity=5.0, option_contract=None) -> Proposal:
    return Proposal(
        order=Order(id="o2", symbol=symbol, side=Side.SELL, quantity=quantity,
                    order_type="MARKET", limit_price=None, product="CNC", strategy_name="macd_crossover"),
        intent=Intent(symbol=symbol, side=Side.SELL, strength=0.7,
                      reason_codes=["macd_bearish_crossover"], stop_hint=110.0, target_hint=90.0),
        score=CompositeScore(rule_score=0.7, ai_score=0.0),
        entry=100.0, mode="LONGTERM", option_contract=option_contract,
    )


@pytest.mark.asyncio
async def test_an_equity_sell_only_exits_what_is_held(mongo):
    store = SuggestionStore(mongo)
    sink = SuggestionSink(store, user_id="alice", source="scan", held={"TCS": 3.0})

    await sink(_sell("RELIANCE"))           # not held: a delivery account cannot short it
    await sink(_sell("TCS", quantity=5.0))  # held 3: capped at 3

    pending = await store.list("alice", status="PENDING")
    assert [(s["symbol"], s["quantity"], s["strategy"]) for s in pending] == [("TCS", 3.0, "macd_crossover")]


@pytest.mark.asyncio
async def test_an_option_sell_is_not_an_equity_short(mongo):
    store = SuggestionStore(mongo)
    sink = SuggestionSink(store, user_id="alice", source="scan", held={})
    await sink(_sell("NIFTY", option_contract={"strike": 100.0}))
    assert len(await store.list("alice", status="PENDING")) == 1


@pytest.mark.asyncio
async def test_an_approved_proposal_opens_a_trade_tagged_with_its_strategy(mongo):
    from backend.engine.persistence import LedgerStore
    from backend.suggestions.service import execute_suggestion

    store = SuggestionStore(mongo)
    proposal = _proposal()
    proposal.order.strategy_name = "breakout"
    await SuggestionSink(store, user_id="alice", source="scan")(proposal)
    suggestion = (await store.list("alice"))[0]

    ledger = LedgerStore(mongo, user_id="alice")
    await execute_suggestion(suggestion, ledger, price=100.0)

    trade = (await ledger.get_trades(status="OPEN"))[0]
    assert (trade["strategy"], trade["suggestion_id"], trade["mode"]) == ("breakout", suggestion["id"], "LONGTERM")


# ---------------------------------------------------------------------------
# Swing built strategies file proposals in the 4 PM scan, for their owner only
# ---------------------------------------------------------------------------

class _BreakoutTodayProvider:
    """Flat at 100 for 59 days, then today's close at 105: a 10-day breakout on the final session."""

    async def history(self, instrument, interval, period):
        from backend.components.shared.models import PriceCandle

        first_day = datetime.now(timezone.utc) - timedelta(days=60)  # last candle yesterday: a closed session
        return [PriceCandle(symbol=instrument.tradingsymbol, timestamp=first_day + timedelta(days=d),
                            open=c, high=c + 1, low=c - 1, close=c, volume=100_000)
                for d, c in enumerate([100.0] * 59 + [105.0])]

    async def quote(self, instrument):
        raise NotImplementedError


_SWING_SPEC = {
    "horizon": "swing", "setup": {"breakout_n": {"days": 10}}, "filters": {}, "side": "long",
    "stop": {"atr_multiple": 2.0}, "target": {"r_multiple": 2.0},
    "max_hold_days": {"days": 10}, "trail_atr": {"multiple": 3.0},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("owner, filed_for", [("alice", {"alice"}), (None, {"alice", "bob"})])
async def test_scan_files_swing_proposal_for_owner_only(mongo, monkeypatch, owner, filed_for):
    from backend.strategies.built import set_active
    from backend.suggestions import scan as scan_module

    monkeypatch.setattr(scan_module, "InstrumentMaster", _FakeMaster)
    monkeypatch.setattr(scan_module, "StoreHistoryProvider", lambda db: _BreakoutTodayProvider())
    monkeypatch.setattr(scan_module, "build_quality_universe", AsyncMock(return_value={}))
    set_active([{"slug": "sw", "spec": _SWING_SPEC, "owner_id": owner}])
    try:
        filed = {}
        for user in ("alice", "bob"):
            filed[user] = [s for s in await scan_universe(mongo, user_id=user, universe=["RELIANCE"])
                           if s["strategy"] == "built:sw"]
    finally:
        set_active([])
    assert {u for u, s in filed.items() if s} == filed_for
    s = filed["alice"][0]
    assert s["symbol"] == "RELIANCE" and s["mode"] == "LONGTERM"
    assert (s["max_hold_days"], s["trail_atr"]) == (10, 3.0)
