from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Intent, Side
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.options.sizing import size_option_intent
from backend.scoring.composite import CompositeScore


class _FakeCtx:
    def __init__(self, closes: list[float], now: datetime) -> None:
        self._closes = closes
        self._now = now

    def history(self, symbol: str, n: int) -> list:
        return [SimpleNamespace(close=c) for c in self._closes[-n:]]

    def now(self) -> datetime:
        return self._now


NOW = datetime(2024, 12, 1, tzinfo=timezone.utc)
CLOSES = [2900.0, 2880.0, 2910.0, 2895.0, 2905.0] * 5  # 25 bars, some variance


def _intent() -> Intent:
    return Intent(
        symbol="RELIANCE", side=Side.SELL, strength=0.8, reason_codes=["oversold_csp"],
        option_flavor="CSP",
    )


def _scored() -> CompositeScore:
    return CompositeScore(rule_score=0.8, ai_score=0.0)


@pytest.fixture
def master():
    return InstrumentMaster(AsyncMongoMockClient()["test_db"])


async def _seed(master, *contracts) -> None:
    """(days_to_expiry, strike) pairs, as the broker's NFO dump lists them."""
    await master.upsert_many([
        Instrument(
            exchange="NFO", tradingsymbol=f"RELIANCE{days}D{int(strike)}PE", name="RELIANCE",
            instrument_token=1000 + i, exchange_token=1000 + i, instrument_type="PE", segment="NFO-OPT",
            lot_size=250, tick_size=0.05,
            expiry=(NOW + timedelta(days=days)).replace(tzinfo=None), strike=strike,
        )
        for i, (days, strike) in enumerate(contracts)
    ])


@pytest.mark.asyncio
async def test_returns_none_when_master_is_none():
    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), 1_000_000.0, None)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_contract_is_listed(master):
    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), 1_000_000.0, master)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_with_fewer_than_20_bars(master):
    await _seed(master, (20, 2760.0))
    ctx = _FakeCtx(CLOSES[:5], NOW)
    result = await size_option_intent(_intent(), _scored(), ctx, 1_000_000.0, master)
    assert result is None


@pytest.mark.asyncio
async def test_picks_the_soonest_real_expiry_and_the_listed_strike_nearest_target(master):
    # spot 2905 -> 5% OTM target 2759.75. The 3-day expiry is too close; the
    # 20-day one lists 2740/2760/2780; a later expiry is ignored.
    await _seed(master, (3, 2760.0), (20, 2740.0), (20, 2760.0), (20, 2780.0), (48, 2760.0))

    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), 1_000_000.0, master)

    assert result is not None
    assert result.contract.strike == 2760.0
    assert (result.contract.expiry.date() - NOW.date()).days == 20
    assert result.order.symbol == "RELIANCE20D2760PE"
    assert result.order.side == Side.SELL and result.order.product == "NRML"
    assert result.order.quantity % 250.0 == 0 and result.order.quantity > 0
    assert result.margin_estimate > 0.0
    assert result.underlying_spot == CLOSES[-1]
    assert result.premium_is_live is False  # no broker: Black-Scholes estimate
    assert result.premium_estimate >= 0.0


@pytest.mark.asyncio
async def test_uses_the_live_premium_when_a_broker_can_price_it(master):
    await _seed(master, (20, 2760.0))
    priced = []

    async def live(contract):
        priced.append(contract.tradingsymbol)
        return 41.35

    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), 1_000_000.0, master, live)
    assert result.premium_estimate == 41.35 and result.premium_is_live is True
    assert priced == ["RELIANCE20D2760PE"]


@pytest.mark.asyncio
async def test_falls_back_to_the_estimate_when_the_broker_cannot_price_it(master):
    await _seed(master, (20, 2760.0))

    async def unpriced(contract):
        return None

    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), 1_000_000.0, master, unpriced)
    assert result.premium_is_live is False and result.premium_estimate >= 0.0


@pytest.mark.asyncio
async def test_returns_none_when_budget_covers_no_lots(master):
    await _seed(master, (20, 2760.0))
    result = await size_option_intent(_intent(), _scored(), _FakeCtx(CLOSES, NOW), account_size=1.0, master=master)
    assert result is None
