"""In-process caches for the daily scan's two slow downloads: a year of
daily prices and a fundamentals snapshot, per stock. Every user's scan asks
for the same ~80 stocks within minutes of each other; without these, 50
users meant 50 identical sets of Yahoo Finance downloads.

Process-local rather than Redis: two years of daily candles for 80 stocks
is a few MB, well past what a managed Redis value should hold, and a cache
miss only costs a download.
"""

import time
from typing import Optional

PRICE_TTL_SECONDS = 60 * 60  # a manual scan mid-session must not freeze today's bar for the day
FUNDAMENTALS_TTL_SECONDS = 24 * 60 * 60


class _TTLCache:
    def __init__(self, ttl_seconds: float, clock=time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict = {}

    def get(self, key):
        hit = self._items.get(key)
        if hit is None:
            return None
        expires, value = hit
        if self._clock() >= expires:
            del self._items[key]
            return None
        return value

    def set(self, key, value) -> None:
        now = self._clock()
        self._items = {k: v for k, v in self._items.items() if v[0] > now}  # drop expired
        self._items[key] = (now + self._ttl, value)


# ponytail: per-worker cache; with several workers each downloads once. Move to Mongo if that matters.
_prices = _TTLCache(PRICE_TTL_SECONDS)
_fundamentals = _TTLCache(FUNDAMENTALS_TTL_SECONDS)


class CachedHistory:
    """Wraps a MarketDataProvider's history(); failures are not cached."""

    def __init__(self, inner, cache: _TTLCache = _prices) -> None:
        self._inner = inner
        self._cache = cache

    async def history(self, instrument, interval: str, period: str):
        key = (instrument.exchange, instrument.tradingsymbol, interval, period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        candles = await self._inner.history(instrument, interval, period)
        if candles:
            self._cache.set(key, candles)
        return candles


class CachedFundamentals:
    """Wraps a FundamentalsProvider's snapshot(); a None or failed snapshot
    is not cached, so a transient Yahoo error doesn't stick for a day."""

    def __init__(self, inner, cache: _TTLCache = _fundamentals) -> None:
        self._inner = inner
        self._cache = cache

    async def snapshot(self, instrument) -> Optional[object]:
        key = (instrument.exchange, instrument.tradingsymbol)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        snapshot = await self._inner.snapshot(instrument)
        if snapshot is not None:
            self._cache.set(key, snapshot)
        return snapshot
