"""backend.engine.runner.size_intents: real scoring + risk sizing wired in
place of Task 4's stub. Covers the two properties the brief requires
regardless of the exact conviction-to-size formula:
- a lower scored.final must never produce a larger position than a higher
  one, all else equal (monotonicity);
- an Intent whose rule floor wasn't met produces zero orders, full stop.
Plus the exposure-limit rejection and missing-stop_hint skip paths.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Intent, Position, Side
from backend.engine.portfolio import Portfolio
from backend.engine.runner import size_intents
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument


class _FakeCtx:
    """Minimal StrategyContext stand-in: only `history()` is used by
    size_intents, to look up the current price for an Intent's symbol."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def history(self, symbol: str, n: int) -> list:
        if symbol not in self._prices:
            return []
        return [SimpleNamespace(close=self._prices[symbol])]


class _FakeStrategy:
    def __init__(self, mode: str, name: str = "fake") -> None:
        self.spec = SimpleNamespace(mode=mode, name=name)


def _no_sentiment_redis():
    redis = AsyncMock()
    redis.get.return_value = None
    return redis


@pytest.mark.asyncio
async def test_rule_floor_not_met_produces_zero_orders_regardless_of_ai():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.1,  # below RULE_FLOOR=0.45
        reason_codes=["weak_signal"], stop_hint=90.0,
    )
    redis = AsyncMock()
    redis.get.return_value = "1.0"  # maximum possible AI sentiment

    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, redis,
        account_size=1_000_000.0, max_exposure=1_000_000.0,
    )
    assert orders == []


@pytest.mark.asyncio
async def test_no_stop_hint_produces_no_order_not_a_crash():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.9,
        reason_codes=["strong_signal"],  # no stop_hint
    )
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0,
    )
    assert orders == []


@pytest.mark.asyncio
async def test_higher_scored_final_never_produces_a_smaller_position():
    async def size_for(strength: float) -> float:
        intent = Intent(
            symbol="RELIANCE", side=Side.BUY, strength=strength,
            reason_codes=["signal"], stop_hint=90.0,
        )
        orders = await size_intents(
            [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
            account_size=1_000_000.0, max_exposure=1_000_000.0,
        )
        assert len(orders) == 1
        return orders[0].quantity

    low_size = await size_for(0.5)   # just above RULE_FLOOR
    high_size = await size_for(1.0)  # maximum conviction
    assert high_size >= low_size
    assert high_size > low_size  # strictly, since the formula is strictly increasing


@pytest.mark.asyncio
async def test_exposure_limit_rejects_when_new_position_would_exceed_max():
    portfolio = Portfolio()
    portfolio.positions["TCS"] = Position(symbol="TCS", quantity=100.0, avg_price=3000.0)
    # existing exposure = 300,000; max_exposure just under that + anything new
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.9,
        reason_codes=["signal"], stop_hint=90.0,
    )
    orders = await size_intents(
        [intent], portfolio, _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=300_000.0,
    )
    assert orders == []


@pytest.mark.asyncio
async def test_product_is_mis_for_intraday_strategy_and_cnc_otherwise():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.9,
        reason_codes=["signal"], stop_hint=90.0,
    )
    ctx = _FakeCtx({"RELIANCE": 100.0})

    intraday_orders = await size_intents(
        [intent], Portfolio(), ctx, {"RELIANCE": _FakeStrategy("INTRADAY")}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0,
    )
    assert intraday_orders[0].product == "MIS"

    longterm_orders = await size_intents(
        [intent], Portfolio(), ctx, {"RELIANCE": _FakeStrategy("LONGTERM")}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0,
    )
    assert longterm_orders[0].product == "CNC"


# ---------------------------------------------------------------------------
# Phase 3 safety rails: per-trade capital cap, kill-switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_trade_cap_rejects_a_trade_whose_notional_exceeds_it():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=1.0,
        reason_codes=["signal"], stop_hint=90.0,
    )
    # Full-conviction sizing against a ₹1,000,000 account would normally
    # produce a notional far above a ₹5,000 per-trade cap.
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, per_trade_cap=5_000.0,
    )
    assert orders == []


@pytest.mark.asyncio
async def test_per_trade_cap_allows_a_trade_within_it():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=1.0,
        reason_codes=["signal"], stop_hint=99.0,  # tight stop -> small size
    )
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, per_trade_cap=10_000_000.0,
    )
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_no_per_trade_cap_means_no_extra_limit():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=1.0,
        reason_codes=["signal"], stop_hint=90.0,
    )
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}), {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0,  # per_trade_cap omitted
    )
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_a_tripped_kill_switch_blocks_intraday_orders():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.9,
        reason_codes=["signal"], stop_hint=90.0,
    )
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}),
        {"RELIANCE": _FakeStrategy("INTRADAY")}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, kill_switch_tripped=True,
    )
    assert orders == []


@pytest.mark.asyncio
async def test_a_tripped_kill_switch_does_not_block_longterm_suggestions():
    """The kill-switch is about auto-executed risk. Long-term proposals stop
    at a human-approved suggestion regardless, so blocking them too would
    only hide information from the person reviewing the inbox."""
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=0.9,
        reason_codes=["signal"], stop_hint=90.0,
    )
    orders = await size_intents(
        [intent], Portfolio(), _FakeCtx({"RELIANCE": 100.0}),
        {"RELIANCE": _FakeStrategy("LONGTERM")}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, kill_switch_tripped=True,
    )
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_order_carries_the_owning_strategys_name():
    intent = Intent(
        symbol="RELIANCE", side=Side.BUY, strength=1.0,
        reason_codes=["signal"], stop_hint=90.0,
    )
    ctx = _FakeCtx({"RELIANCE": 100.0})
    strategy = _FakeStrategy(mode="INTRADAY", name="volume_surge")
    orders = await size_intents(
        [intent], Portfolio(), ctx, {"RELIANCE": strategy}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0,
    )
    assert len(orders) == 1
    assert orders[0].strategy_name == "volume_surge"


def test_order_strategy_name_defaults_to_none():
    from backend.core.models import Order, Side
    order = Order(id="x", symbol="RELIANCE", side=Side.BUY, quantity=1.0, order_type="MARKET")
    assert order.strategy_name is None


# ---------------------------------------------------------------------------
# option_flavor dispatch (Phase 5b)
# ---------------------------------------------------------------------------

class _FakeCtxWithNow:
    """Same shape as this file's `_FakeCtx`, plus the `.now()` method
    size_option_intent needs and per-symbol price *series* (not a single
    price) so realized_volatility has enough history to compute."""

    def __init__(self, prices: dict[str, list[float]], now: datetime) -> None:
        self._series = prices
        self._now = now

    def history(self, symbol: str, n: int) -> list:
        series = self._series.get(symbol, [])
        return [SimpleNamespace(close=c) for c in series[-n:]]

    def now(self) -> datetime:
        return self._now


_NOW = datetime(2024, 12, 1, tzinfo=timezone.utc)
_CLOSES = [2900.0, 2880.0, 2910.0, 2895.0, 2905.0] * 5


@pytest.mark.asyncio
async def test_option_flavored_intent_skips_equity_sizing_and_needs_no_stop_hint():
    intent = Intent(
        symbol="RELIANCE", side=Side.SELL, strength=0.8, reason_codes=["oversold_csp"],
        option_flavor="CSP",  # no stop_hint -- would be skipped by the equity path
    )
    ctx = _FakeCtxWithNow({"RELIANCE": _CLOSES}, _NOW)
    orders = await size_intents(
        [intent], Portfolio(), ctx, {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, master=None,
    )
    # master=None -> size_option_intent returns None -> no order, but it
    # must not fall through to the equity path and crash on stop_hint=None.
    assert orders == []


@pytest.mark.asyncio
async def test_option_flavored_intent_produces_an_order_with_a_synced_contract():
    master = InstrumentMaster(AsyncMongoMockClient()["test_db"])
    # A listed contract as the broker's NFO dump reports it: an expiry more
    # than MIN_DAYS_TO_EXPIRY out and a strike near 5% below spot.
    expiry = (_NOW + timedelta(days=20)).date()
    strike = round(_CLOSES[-1] * 0.95 / 20) * 20
    tradingsymbol = "RELIANCE26OCT2760PE"
    await master.upsert_many([Instrument(
        exchange="NFO", tradingsymbol=tradingsymbol, name="RELIANCE",
        instrument_token=1, exchange_token=1, instrument_type="PE", segment="NFO-OPT",
        lot_size=250, tick_size=0.05,
        expiry=datetime.combine(expiry, datetime.min.time()), strike=strike,
    )])

    intent = Intent(
        symbol="RELIANCE", side=Side.SELL, strength=0.8, reason_codes=["oversold_csp"],
        option_flavor="CSP",
    )
    ctx = _FakeCtxWithNow({"RELIANCE": _CLOSES}, _NOW)

    captured = []

    async def sink(proposal):
        captured.append(proposal)
        return False  # sink owns it, same contract as the equity/LONGTERM path

    orders = await size_intents(
        [intent], Portfolio(), ctx, {}, _no_sentiment_redis(),
        account_size=1_000_000.0, max_exposure=1_000_000.0, master=master, order_sink=sink,
    )

    assert orders == []  # sink took ownership
    assert len(captured) == 1
    proposal = captured[0]
    assert proposal.order.symbol == tradingsymbol
    assert proposal.order.product == "NRML"
    assert proposal.option_contract is not None
    assert proposal.option_contract["strike"] == strike
    assert proposal.option_contract["option_type"] == "PE"
    assert proposal.entry == proposal.option_contract["premium_estimate"]
