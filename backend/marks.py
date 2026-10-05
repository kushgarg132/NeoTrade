"""Current prices for a set of symbols, best-effort.

A missing quote is normal (delisted symbol, provider hiccup, market closed
on a holiday) and must never be reported as a price of zero -- callers treat
an absent symbol as "no mark", which costs them an unrealized number rather
than inventing a loss.

Prices come from the shared Redis cache `quote:{SYMBOL}` first. The ingest
worker (backend/datalayer/prices.py) keeps it fresh for held, watched and
Nifty 200 names; anything missing or older than `max_age_seconds` is fetched
here and written back, so the other worker and the next caller reuse it.
"""

import asyncio
import json
import logging
import time
from typing import Iterable, Optional

from backend.data.providers.yfinance_provider import YFinanceProvider
from backend.instruments.master import InstrumentMaster

logger = logging.getLogger(__name__)

# The P&L cards are the first thing on the statement, and they are read in a
# glance during the session. A slow upstream must cost the unrealised line,
# never the whole page: past this the marks are simply absent, which the
# callers already treat as "no mark" rather than a price of zero.
TIMEOUT_SECONDS = 4.0

QUOTE_KEY = "quote:{}"
DEFAULT_MAX_AGE_SECONDS = 60
# Paths that place an order at this price: never older than this.
ORDER_MAX_AGE_SECONDS = 20
WRITE_THROUGH_TTL_SECONDS = 120


def _redis():
    from backend.database import db

    return db.redis


async def cached_quotes(redis, symbols: list[str], max_age_seconds: float) -> dict[str, float]:
    """Cached last prices no older than `max_age_seconds`; never raises."""
    if redis is None or not symbols:
        return {}
    try:
        raws = await redis.mget([QUOTE_KEY.format(s) for s in symbols])
    except Exception as exc:
        logger.warning("quote cache read failed: %s", exc)
        return {}
    now, found = time.time(), {}
    for symbol, raw in zip(symbols, raws):
        if raw:
            quote = json.loads(raw)
            if quote.get("ltp") and now - quote["at"] <= max_age_seconds:
                found[symbol] = float(quote["ltp"])
    return found


async def store_quotes(redis, quotes: dict[str, tuple[float, Optional[float]]], ttl_seconds: int) -> None:
    """`quotes` is symbol -> (last price, previous close or None)."""
    if redis is None or not quotes:
        return
    at = time.time()
    try:
        async with redis.pipeline(transaction=False) as pipe:
            for symbol, (ltp, prev_close) in quotes.items():
                pipe.set(QUOTE_KEY.format(symbol), json.dumps({"ltp": ltp, "prev_close": prev_close, "at": at}),
                         ex=ttl_seconds)
            await pipe.execute()
    except Exception as exc:
        logger.warning("quote cache write failed: %s", exc)


async def mark_prices(db, symbols: Iterable[str], max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> dict[str, float]:
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return {}

    redis = _redis()
    found = await cached_quotes(redis, symbols, max_age_seconds)
    missing = [s for s in symbols if s not in found]
    if not missing:
        return found

    master = InstrumentMaster(db)
    provider = YFinanceProvider()

    async def _one(symbol: str):
        try:
            instrument = await master.get("NSE", symbol)
            if instrument is None:
                return symbol, None
            quote = await provider.quote(instrument)
            return symbol, quote.get("last_price")
        except Exception as exc:
            logger.warning("no mark price for %s: %s", symbol, exc)
            return symbol, None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(_one(symbol) for symbol in missing)), timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("mark prices timed out for %d symbol(s)", len(missing))
        return found

    fetched = {symbol: float(price) for symbol, price in results if price}
    await store_quotes(redis, {s: (p, None) for s, p in fetched.items()}, WRITE_THROUGH_TTL_SECONDS)
    return {**found, **fetched}
