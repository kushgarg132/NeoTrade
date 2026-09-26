"""The scan's per-process caches: one download per stock across every
user's scan, expiry, and failures never cached."""

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

from backend.data.feeds.historical import period_for
from backend.data.providers.cached import CachedFundamentals, CachedHistory, _TTLCache


def _inst(symbol="SBIN"):
    return MagicMock(exchange="NSE", tradingsymbol=symbol)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def test_history_is_downloaded_once_until_it_expires():
    clock = _Clock()
    inner = MagicMock(history=AsyncMock(return_value=["candle"]))
    cached = CachedHistory(inner, cache=_TTLCache(60, clock=clock))

    assert await cached.history(_inst(), "1d", "2y") == ["candle"]
    assert await cached.history(_inst(), "1d", "2y") == ["candle"]
    assert inner.history.await_count == 1

    await cached.history(_inst("TCS"), "1d", "2y")
    assert inner.history.await_count == 2  # different stock, own entry

    clock.t = 61
    await cached.history(_inst(), "1d", "2y")
    assert inner.history.await_count == 3


async def test_empty_history_and_missing_fundamentals_are_not_cached():
    inner = MagicMock(history=AsyncMock(return_value=[]), snapshot=AsyncMock(return_value=None))
    history = CachedHistory(inner, cache=_TTLCache(60))
    fundamentals = CachedFundamentals(inner, cache=_TTLCache(60))
    for _ in range(2):
        await history.history(_inst(), "1d", "2y")
        await fundamentals.snapshot(_inst())
    assert inner.history.await_count == 2
    assert inner.snapshot.await_count == 2


def test_daily_period_is_the_smallest_that_reaches_back_far_enough():
    now = datetime(2026, 9, 26)
    assert period_for("1d", now - timedelta(days=400), now) == "2y"
    assert period_for("1d", now - timedelta(days=20), now) == "1mo"
    assert period_for("1d", now - timedelta(days=5000), now) == "max"
    assert period_for("5m", now - timedelta(days=20), now) == "max"
