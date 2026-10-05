"""Takes a running intraday run onto the game plan's new stocks in play:
resolve them, subscribe the feed, let the strategies trade them, and hand
back today's bars when the feed won't replay them itself. Built by
_launch_run, called by runner.run when a plan version adds symbols."""

import logging
from datetime import date, datetime, timedelta, timezone

from backend.core.models import Bar
from backend.engine.session import IST

logger = logging.getLogger(__name__)
CANDLE = timedelta(minutes=5)


def make_expand(master, feed, provider, strategies, symbol_for_token: dict[int, str], today: date,
                now_fn=lambda: datetime.now(timezone.utc)):
    async def expand(symbols: list[str]) -> list[Bar]:
        if not hasattr(feed, "add"):
            logger.info("feed %s cannot add symbols mid-run; skipped %s", type(feed).__name__, symbols)
            return []
        instruments = [i for s in symbols if (i := await master.get("NSE", s)) is not None]
        if not instruments:
            return []
        for i in instruments:
            symbol_for_token[i.instrument_token] = i.tradingsymbol
        needs_backfill = feed.add(instruments)
        names = [i.tradingsymbol for i in instruments]
        for strategy in strategies:
            if strategy.spec.mode == "INTRADAY" and hasattr(strategy, "extend_universe"):
                strategy.extend_universe(names)
        if not needs_backfill:
            return []
        now = now_fn()
        bars = []
        for i in instruments:
            try:
                candles = await provider.history(i, interval="5m", period="5d")
            except Exception as exc:
                logger.warning("no backfill for %s: %s", i.tradingsymbol, exc)
                continue
            bars += [Bar(instrument_token=i.instrument_token, timeframe="5m", timestamp=c.timestamp, open=c.open,
                         high=c.high, low=c.low, close=c.close, volume=c.volume, warmup=True)
                     for c in candles if c.timestamp.astimezone(IST).date() == today and c.timestamp + CANDLE <= now]
        logger.info("added %s to the run (%d backfill bars)", names, len(bars))
        return sorted(bars, key=lambda b: b.timestamp)
    return expand
