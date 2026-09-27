"""MarketDataProvider backed by Kite Connect's REST API. Real pykiteconnect
API surface used (verified against the installed 5.2.1 package's source):

- `KiteConnect.historical_data(instrument_token, from_date, to_date,
  interval, continuous=False, oi=False)` -> GET
  https://api.kite.trade/instruments/historical/{instrument_token}/{interval}
  ("market.historical"). Unlike `YFinanceProvider` (Task 1), Kite takes an
  explicit `from_date`/`to_date` pair, not a yfinance-style period string
  like "1y" -- `_period_to_range()` below does that conversion. Returns a
  list of dicts: `{date, open, high, low, close, volume[, oi]}`.
- `KiteConnect.quote(*instruments)` -> GET https://api.kite.trade/quote
  ("market.quote"), instruments given as `"EXCHANGE:TRADINGSYMBOL"` strings.
  Returns a dict keyed by that same string, whose value carries `last_price`
  and a nested `ohlc: {open, high, low, close}`.

Both are synchronous (requests-based) SDK calls -- each is run via
`asyncio.to_thread` so they never block the event loop.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable

from backend.components.shared.models import PriceCandle
from backend.instruments.models import Instrument

# This project's interval convention (see YFinanceProvider/strategies) is
# yfinance's own strings. Kite's documented interval values are "minute",
# "3minute", "5minute", "10minute", "15minute", "30minute", "60minute",
# "day" -- https://kite.trade/docs/connect/v3/historical/#historical-candle-format
_INTERVAL_MAP = {
    "1m": "minute",
    "5m": "5minute",
    "15m": "15minute",
    "30m": "30minute",
    "60m": "60minute",
    "1h": "60minute",
    "1d": "day",
}

# Approximate day-widths for this project's yfinance-style period strings.
# Kite has no period shorthand at all -- it always wants explicit dates.
_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 182,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    # HistoricalFeed asks for "max" on intraday timeframes; a year is what
    # the backtest gate's window needs.
    "max": 365,
}
# Kite's documented cap on one historical request's span, by interval
# (https://kite.trade/docs/connect/v3/historical/): 60 days of minute
# candles, 100 of 3-60 minute ones, 2000 of daily. Longer ranges are
# fetched in windows under the cap.
_MAX_DAYS_PER_REQUEST = {"minute": 60, "day": 2000}
_DEFAULT_MAX_DAYS = 100


class KiteProvider:
    def __init__(
        self,
        kite_client_factory: Callable[[], "KiteConnect"],  # noqa: F821
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._kite_client_factory = kite_client_factory
        self._now_fn = now_fn

    @staticmethod
    def _kite_interval(interval: str) -> str:
        try:
            return _INTERVAL_MAP[interval]
        except KeyError:
            raise ValueError(
                f"Unsupported interval for Kite: {interval!r}. Supported: {sorted(_INTERVAL_MAP)}"
            ) from None

    def _period_to_range(self, period: str) -> tuple[datetime, datetime]:
        try:
            days = _PERIOD_DAYS[period]
        except KeyError:
            raise ValueError(f"Unsupported period for Kite: {period!r}. Supported: {sorted(_PERIOD_DAYS)}") from None
        to_date = self._now_fn()
        return to_date - timedelta(days=days), to_date

    async def history(self, instrument: Instrument, interval: str, period: str) -> list[PriceCandle]:
        kite_interval = self._kite_interval(interval)
        from_date, to_date = self._period_to_range(period)

        kite = self._kite_client_factory()
        window = timedelta(days=_MAX_DAYS_PER_REQUEST.get(kite_interval, _DEFAULT_MAX_DAYS) - 1)
        rows, start = [], from_date
        while start < to_date:
            end = min(start + window, to_date)
            rows += await asyncio.to_thread(
                kite.historical_data, instrument.instrument_token, start, end, kite_interval, False, False
            )
            start = end + timedelta(seconds=1)
        return [
            PriceCandle(
                symbol=instrument.tradingsymbol,
                timestamp=row["date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                adj_close=row["close"],
                volume=row["volume"],
            )
            for row in rows
        ]

    async def quote(self, instrument: Instrument) -> dict:
        key = f"{instrument.exchange}:{instrument.tradingsymbol}"
        kite = self._kite_client_factory()
        response = await asyncio.to_thread(kite.quote, key)
        data = response[key]
        last_price = data["last_price"]
        ohlc = data.get("ohlc", {})
        return {
            "symbol": instrument.tradingsymbol,
            "last_price": last_price,
            "open": ohlc.get("open", last_price),
            "high": ohlc.get("high", last_price),
            "low": ohlc.get("low", last_price),
            "close": ohlc.get("close", last_price),
            "volume": data.get("volume", 0),
        }
