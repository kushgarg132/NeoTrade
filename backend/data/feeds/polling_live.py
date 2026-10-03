"""DataFeed stand-in for KiteTickerFeed (backend/data/feeds/live_kite.py)
until real Kite credentials exist. Polls `MarketDataProvider.quote()` on a
fixed interval and synthesizes one Bar per instrument per poll -- same
DataFeed protocol, so `backend.engine.runner.run` works identically against
either. This is what makes Task 6's paper trading engine runnable today
against real (if delayed/quote-only) market data, via the already-working
YFinanceProvider from Task 1.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

from backend.core.models import Bar
from backend.data.protocols import MarketDataProvider
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)


class PollingLiveFeed:
    def __init__(
        self,
        provider: MarketDataProvider,
        instruments: list[Instrument],
        timeframe: str,
        poll_interval_seconds: float = 60.0,
        sleep_fn: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._instruments = instruments
        self._timeframe = timeframe
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep_fn = sleep_fn
        self.symbol_for_token: dict[int, str] = {
            instrument.instrument_token: instrument.tradingsymbol for instrument in instruments
        }

    async def __aiter__(self) -> AsyncIterator[Bar]:
        while True:
            now = datetime.now(timezone.utc)
            for instrument in self._instruments:
                try:
                    quote = await self._provider.quote(instrument)
                except Exception as exc:
                    # One delisted or renamed symbol must not end the whole run.
                    logger.warning("no quote for %s, skipped this poll: %s", instrument.tradingsymbol, exc)
                    continue
                last_price = quote["last_price"]
                yield Bar(
                    instrument_token=instrument.instrument_token,
                    timeframe=self._timeframe,
                    timestamp=now,
                    open=quote.get("open", last_price),
                    high=quote.get("high", last_price),
                    low=quote.get("low", last_price),
                    close=quote.get("close", last_price),
                    volume=quote.get("volume", 0.0),
                )
            await self._sleep_fn(self._poll_interval_seconds)
