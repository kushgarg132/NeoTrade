"""HistoricalFeed replays multiple instruments' history as one bar stream.

A real universe has 80+ symbols; yfinance returning empty data for one
delisted or renamed symbol is routine, not exceptional. One instrument's
fetch failure must not discard every other instrument's bars -- both the
suggestion scan and the backtester iterate the whole feed in one pass, so a
single bad symbol used to abort the entire run.
"""

from datetime import datetime, timezone

import pytest

from backend.core.models import PriceCandle
from backend.data.feeds.historical import HistoricalFeed
from backend.instruments.models import Instrument

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _instrument(symbol: str, token: int) -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=token,
        exchange_token=token, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )


def _candle(symbol: str, day: int) -> PriceCandle:
    return PriceCandle(
        symbol=symbol, timestamp=datetime(2024, 1, 1 + day, tzinfo=timezone.utc),
        open=100.0, high=101.0, low=99.0, close=100.5, volume=1000,
    )


class _PartiallyFailingProvider:
    """Raises for one symbol, like yfinance does for a delisted/renamed one."""

    def __init__(self, failing_symbols):
        self.failing_symbols = set(failing_symbols)
        self.calls = []

    async def history(self, instrument, interval, period):
        self.calls.append(instrument.tradingsymbol)
        if instrument.tradingsymbol in self.failing_symbols:
            raise ValueError(f"No price data found for {instrument.tradingsymbol}.NS")
        return [_candle(instrument.tradingsymbol, day) for day in range(3)]

    async def quote(self, instrument):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_a_failing_symbol_does_not_discard_the_others():
    instruments = [_instrument("RELIANCE", 1), _instrument("GMRINFRA", 2), _instrument("TCS", 3)]
    provider = _PartiallyFailingProvider(failing_symbols=["GMRINFRA"])
    feed = HistoricalFeed(provider, instruments, start=T0, end=T0.replace(day=5), timeframe="1d")

    bars = [bar async for bar in feed]

    symbols_seen = {feed.symbol_for_token[bar.instrument_token] for bar in bars}
    assert symbols_seen == {"RELIANCE", "TCS"}, "the failing symbol's siblings must still yield bars"
    assert provider.calls == ["RELIANCE", "GMRINFRA", "TCS"], "every instrument is still attempted"


@pytest.mark.asyncio
async def test_bars_stay_sorted_across_instruments_when_one_fails():
    instruments = [_instrument("RELIANCE", 1), _instrument("GMRINFRA", 2), _instrument("TCS", 3)]
    provider = _PartiallyFailingProvider(failing_symbols=["GMRINFRA"])
    feed = HistoricalFeed(provider, instruments, start=T0, end=T0.replace(day=5), timeframe="1d")

    bars = [bar async for bar in feed]

    assert [bar.timestamp for bar in bars] == sorted(bar.timestamp for bar in bars)


@pytest.mark.asyncio
async def test_when_every_symbol_fails_the_feed_yields_nothing_not_an_error():
    instruments = [_instrument("GMRINFRA", 1)]
    provider = _PartiallyFailingProvider(failing_symbols=["GMRINFRA"])
    feed = HistoricalFeed(provider, instruments, start=T0, end=T0.replace(day=5), timeframe="1d")

    assert [bar async for bar in feed] == []


@pytest.mark.asyncio
async def test_no_failures_behaves_exactly_as_before():
    instruments = [_instrument("RELIANCE", 1), _instrument("TCS", 3)]
    provider = _PartiallyFailingProvider(failing_symbols=[])
    feed = HistoricalFeed(provider, instruments, start=T0, end=T0.replace(day=5), timeframe="1d")

    bars = [bar async for bar in feed]

    assert len(bars) == 6


@pytest.mark.asyncio
async def test_window_compares_aware_times_as_instants():
    """_naive stripped tzinfo without converting: an IST candle at 09:15
    (03:45 UTC) fell outside a UTC window ending 04:00 by wall clock."""
    from datetime import timedelta

    ist = timezone(timedelta(hours=5, minutes=30))

    class _IstProvider(_PartiallyFailingProvider):
        async def history(self, instrument, interval, period):
            return [PriceCandle(symbol="TCS", timestamp=datetime(2024, 1, 2, 9, 15, tzinfo=ist),
                                open=1, high=1, low=1, close=1, volume=1)]

    feed = HistoricalFeed(_IstProvider([]), [_instrument("TCS", 3)],
                          start=datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc),
                          end=datetime(2024, 1, 2, 4, 0, tzinfo=timezone.utc), timeframe="5m")
    assert len([bar async for bar in feed]) == 1
