"""DataFeed backed by a MarketDataProvider (Task 1): pulls each instrument's
history once up front and replays it as one chronologically-sorted Bar
stream. This is what makes backtesting possible against the yfinance
provider (or any other MarketDataProvider) that already exists.

Deviation from the brief: `MarketDataProvider.history()` (Task 1's actual
protocol, backend/data/protocols.py) takes yfinance-shaped
`interval`/`period` strings, not a `start`/`end` date range. To honor this
task's stated `HistoricalFeed(provider, instruments, date range, timeframe)`
shape without inventing a start/end-aware provider method Task 1 doesn't
have, this class still accepts `start`/`end` datetimes, requests the
broadest period ("max") from the provider, and filters the returned candles
to that closed range itself. Real intraday period limits on the actual
yfinance API aren't exercised here since tests use a fake provider.
"""

import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from backend.core.models import Bar
from backend.data.protocols import MarketDataProvider
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_FETCHES = 10
# yfinance's fixed periods, smallest first, with the days each reaches back.
_DAILY_PERIODS = [("1mo", 30), ("3mo", 91), ("6mo", 182), ("1y", 365), ("2y", 730), ("5y", 1826), ("10y", 3652)]


def period_for(timeframe: str, start: datetime, now: datetime) -> str:
    if timeframe != "1d":
        return "max"
    days_back = (_naive(now) - _naive(start)).days + 7  # a week of slack for holidays
    return next((period for period, days in _DAILY_PERIODS if days >= days_back), "max")


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


class HistoricalFeed:
    def __init__(
        self,
        provider: MarketDataProvider,
        instruments: list[Instrument],
        start: datetime,
        end: datetime,
        timeframe: str,
        now: Optional[datetime] = None,
    ) -> None:
        self._provider = provider
        self._period = period_for(timeframe, start, now or datetime.now(timezone.utc))
        self._instruments = instruments
        self._start = start
        self._end = end
        self._timeframe = timeframe
        self.symbol_for_token: dict[int, str] = {
            instrument.instrument_token: instrument.tradingsymbol for instrument in instruments
        }

    async def _candles(self, instrument: Instrument, semaphore: asyncio.Semaphore):
        # A real universe has 80+ symbols; yfinance returning nothing for
        # one delisted/renamed one is routine, not exceptional -- it must
        # not discard every other instrument's history in the same batch.
        async with semaphore:
            try:
                return instrument, await self._provider.history(instrument, self._timeframe, self._period)
            except Exception as exc:
                logger.warning("skipping %s: %s", instrument.tradingsymbol, exc)
                return instrument, []

    async def __aiter__(self) -> AsyncIterator[Bar]:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
        began = time.monotonic()
        fetched = await asyncio.gather(*(self._candles(i, semaphore) for i in self._instruments))
        logger.info(
            "historical feed: %d/%d symbols with data, %d candles, %s, in %.1fs",
            sum(1 for _, c in fetched if c), len(fetched), sum(len(c) for _, c in fetched),
            self._timeframe, time.monotonic() - began,
        )

        bars: list[Bar] = []
        for instrument, candles in fetched:
            for candle in candles:
                if not (_naive(self._start) <= _naive(candle.timestamp) <= _naive(self._end)):
                    continue
                bars.append(Bar(
                    instrument_token=instrument.instrument_token,
                    timeframe=self._timeframe,
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                ))

        bars.sort(key=lambda bar: bar.timestamp)
        for bar in bars:
            yield bar
