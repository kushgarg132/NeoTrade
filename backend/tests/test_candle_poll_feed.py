"""CandlePollingFeed: real 5-minute candles, each yielded once, only after it closes."""

from datetime import datetime, timedelta

import pytest

from backend.components.shared.models import PriceCandle
from backend.data.feeds.candle_poll import CandlePollingFeed
from backend.engine.session import IST
from backend.instruments.models import Instrument

OPEN = datetime(2026, 10, 5, 9, 15, tzinfo=IST)


def _instrument(symbol, token):
    return Instrument(exchange="NSE", tradingsymbol=symbol, name=symbol, instrument_token=token,
                      exchange_token=token, instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)


def _candle(i):
    return PriceCandle(symbol="X", timestamp=OPEN + timedelta(minutes=5 * i), open=100 + i,
                       high=101 + i, low=99 + i, close=100.5 + i, volume=1000)


class _Provider:
    """Each poll sees one more candle than the last; the newest is still forming."""

    def __init__(self):
        self.polls = {}

    async def history(self, instrument, interval, period):
        assert (interval, period) == ("5m", "1d")
        if instrument.tradingsymbol == "GONE":
            raise ValueError("No price data found")
        n = self.polls[instrument.tradingsymbol] = self.polls.get(instrument.tradingsymbol, 0) + 1
        return [_candle(i) for i in range(n + 2)]


@pytest.mark.asyncio
async def test_yields_each_closed_candle_once_in_order_and_skips_bad_symbols():
    clock = {"now": OPEN + timedelta(minutes=12)}  # candles 0 and 1 closed, 2 forming

    async def sleep(seconds):
        clock["now"] += timedelta(minutes=5)

    feed = CandlePollingFeed(_Provider(), [_instrument("RELIANCE", 1), _instrument("GONE", 2)],
                             sleep_fn=sleep, now_fn=lambda: clock["now"])
    bars = []
    async for bar in feed:
        bars.append(bar)
        if len(bars) == 4:
            break

    assert [b.timestamp for b in bars] == [OPEN + timedelta(minutes=5 * i) for i in range(4)]
    assert {b.instrument_token for b in bars} == {1}
    assert bars[0].timeframe == "5m" and bars[0].close == 100.5
