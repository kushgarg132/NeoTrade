"""Real 5-minute bars without a broker session.

PollingLiveFeed turns a quote into a bar on every poll, which is right for
nothing intraday: a 5-minute strategy fed a daily quote every minute reads
the day's open/high/low as one bar's. This polls the provider's own 5-minute
candles instead (yfinance, ~15 minutes delayed for NSE) and yields each one
once, after it has closed -- the same shape a broker ticker feed produces,
just late. The first poll yields everything so far today, so a run started
or restarted mid-session still sees the opening range.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable, Optional

from backend.core.models import Bar
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)

CANDLE = timedelta(minutes=5)
# Poll just after each 5-minute boundary, when the candle before it is final.
SETTLE_SECONDS = 15


class CandlePollingFeed:
    source = "yfinance 5m, ~15 min delayed"

    def __init__(
        self,
        provider,
        instruments: list[Instrument],
        timeframe: str = "5m",
        sleep_fn: Callable[[float], "asyncio.Future"] = asyncio.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._instruments = instruments
        self._timeframe = timeframe
        self._sleep_fn = sleep_fn
        self._now_fn = now_fn
        self._last: dict[int, datetime] = {}  # instrument_token -> newest candle yielded
        self.symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments}

    async def _closed_candles(self, instrument: Instrument, now: datetime) -> list:
        try:
            candles = await self._provider.history(instrument, interval="5m", period="1d")
        except Exception as exc:
            logger.warning("no 5m candles for %s, skipped this poll: %s", instrument.tradingsymbol, exc)
            return []
        last: Optional[datetime] = self._last.get(instrument.instrument_token)
        return [
            c for c in candles
            if c.timestamp + CANDLE <= now and (last is None or c.timestamp > last)
        ]

    async def __aiter__(self) -> AsyncIterator[Bar]:
        while True:
            now = self._now_fn()
            for instrument in self._instruments:
                for candle in await self._closed_candles(instrument, now):
                    self._last[instrument.instrument_token] = candle.timestamp
                    yield Bar(
                        instrument_token=instrument.instrument_token,
                        timeframe=self._timeframe,
                        timestamp=candle.timestamp,
                        open=candle.open, high=candle.high, low=candle.low, close=candle.close,
                        volume=candle.volume,
                    )
            seconds = CANDLE.total_seconds()
            await self._sleep_fn(seconds - (self._now_fn().timestamp() % seconds) + SETTLE_SECONDS)
