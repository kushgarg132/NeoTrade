"""build_quality_universe: exclusion-on-failure, threshold filtering, and the
concurrency cap -- driven entirely by a fake FundamentalsProvider, no
network."""

import asyncio

from backend.instruments.models import Instrument
from backend.data.fundamentals.scores import quality_score
from backend.data.fundamentals.protocols import FundamentalSnapshot
from backend.data.fundamentals.universe import build_quality_universe


def _instrument(symbol: str) -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol,
        instrument_token=hash(symbol) % 1_000_000, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


_HIGH_QUALITY = FundamentalSnapshot(
    symbol="_", return_on_equity=0.2, return_on_assets=0.1,
    revenue_growth=0.1, debt_to_equity=0.5, earnings_yield=0.12,
)
_LOW_QUALITY = FundamentalSnapshot(symbol="_", earnings_yield=0.01)
assert quality_score(_HIGH_QUALITY) > 0.5 > quality_score(_LOW_QUALITY)


class FakeProvider:
    """Returns `_HIGH_QUALITY` or `_LOW_QUALITY` (with the real symbol
    substituted in) per `snapshots` lookup, raises for symbols in `raising`,
    returns None for symbols in `none_for`. Tracks peak concurrent
    `snapshot()` calls in-flight so the semaphore cap can be asserted."""

    def __init__(self, snapshots: dict[str, FundamentalSnapshot], raising=(), none_for=(), delay=0.0):
        self.snapshots = snapshots
        self.raising = set(raising)
        self.none_for = set(none_for)
        self.delay = delay
        self._in_flight = 0
        self.peak_in_flight = 0

    async def snapshot(self, instrument: Instrument):
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            symbol = instrument.tradingsymbol
            if symbol in self.raising:
                raise RuntimeError(f"boom: {symbol}")
            if symbol in self.none_for:
                return None
            return self.snapshots[symbol].model_copy(update={"symbol": symbol})
        finally:
            self._in_flight -= 1


async def test_build_quality_universe_excludes_none_and_raising():
    instruments = [_instrument("A"), _instrument("B"), _instrument("C")]
    provider = FakeProvider(
        snapshots={"A": _HIGH_QUALITY, "B": _HIGH_QUALITY, "C": _HIGH_QUALITY},
        raising=["B"], none_for=["C"],
    )

    result = await build_quality_universe(instruments, provider, min_quality_score=0.0)

    assert result == {"A": quality_score(_HIGH_QUALITY.model_copy(update={"symbol": "A"}))}


async def test_build_quality_universe_applies_threshold():
    instruments = [_instrument("HIGH"), _instrument("LOW")]
    provider = FakeProvider(snapshots={"HIGH": _HIGH_QUALITY, "LOW": _LOW_QUALITY})

    result = await build_quality_universe(instruments, provider, min_quality_score=0.5)

    assert result == {"HIGH": quality_score(_HIGH_QUALITY.model_copy(update={"symbol": "HIGH"}))}


async def test_build_quality_universe_caps_concurrency():
    symbols = [f"SYM{i}" for i in range(25)]
    instruments = [_instrument(s) for s in symbols]
    provider = FakeProvider(snapshots={s: _HIGH_QUALITY for s in symbols}, delay=0.01)

    result = await build_quality_universe(instruments, provider, min_quality_score=0.0)

    assert len(result) == 25
    assert provider.peak_in_flight <= 10
    assert provider.peak_in_flight > 1  # actually ran concurrently, not serialized
