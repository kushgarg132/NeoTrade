"""History and fundamentals read from the shared stores the ingest worker
fills (backend/datalayer/bars.py), falling back to yfinance on a miss.

Only completed daily NSE bars live in the store: an intraday interval, a
non-NSE instrument, a symbol the store does not cover, stale bars, or a
period reaching further back than the store holds all go to the fallback.
"""

from datetime import datetime, time, timedelta, timezone
from typing import Optional

from backend.components.shared.models import PriceCandle
from backend.datalayer import bars
from backend.engine.session import IST
from backend.screening.protocols import FundamentalSnapshot

_PERIOD_DAYS = {"1mo": 30, "3mo": 91, "6mo": 182, "1y": 365, "2y": 730}
_COVER_SLACK = timedelta(days=10)  # the first trading day after `since` can be a week+ later


class StoreHistoryProvider:
    def __init__(self, db, fallback=None) -> None:
        from backend.data.providers.yfinance_provider import YFinanceProvider

        self._db = db
        self._fallback = fallback or YFinanceProvider()

    async def history(self, instrument, interval: str, period: str) -> list[PriceCandle]:
        days = _PERIOD_DAYS.get(period)
        if interval == "1d" and days and instrument.exchange == "NSE":
            since = bars.today_ist() - timedelta(days=days)
            frame = (await bars.read(self._db, [instrument.tradingsymbol], since)).get(instrument.tradingsymbol)
            if frame is not None and frame.index[0].date() <= since + _COVER_SLACK:
                return [
                    PriceCandle(
                        symbol=f"{instrument.tradingsymbol}.NS",
                        timestamp=datetime.combine(index.date(), time(), IST),
                        open=row.open, high=row.high, low=row.low, close=row.close,
                        adj_close=row.close, volume=int(row.volume),
                    )
                    for index, row in frame.iterrows()
                ]
        return await self._fallback.history(instrument, interval, period)

    async def quote(self, instrument) -> dict:
        return await self._fallback.quote(instrument)


class StoreFundamentals:
    def __init__(self, db, fallback=None) -> None:
        from backend.screening.providers.yfinance_fundamentals import YFinanceFundamentalsProvider

        self._db = db
        self._fallback = fallback or YFinanceFundamentalsProvider()

    async def snapshot(self, instrument) -> Optional[FundamentalSnapshot]:
        doc = await self._db[bars.FUNDAMENTALS].find_one({"_id": instrument.tradingsymbol})
        if doc and _aware(doc["as_of"]) >= datetime.now(IST) - bars.FUNDAMENTALS_MAX_AGE:
            return FundamentalSnapshot(**{k: v for k, v in doc.items() if k not in ("_id", "as_of")})
        return await self._fallback.snapshot(instrument)


def _aware(dt: datetime) -> datetime:
    # mongomock (tests) hands datetimes back naive UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
