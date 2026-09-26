"""Tick-to-bar aggregation shared by every broker's streaming feed.

A broker feed hands this class ticks -- dicts carrying `instrument_token`,
`last_price` and optionally `volume_traded` (the broker's cumulative
volume for the day) -- via `_ingest`, and its `__aiter__` calls
`_flush_due_windows` on a clock to yield `Bar`s.

Bar aggregation is deliberately clock-driven, not tick-driven: a periodic
flush closes each instrument's current window at its clock boundary
regardless of whether a new tick has arrived, so a quiet symbol still emits
a bar (using its last known price, flat, zero volume) instead of silently
never producing one. `now_fn`/`sleep_fn` are injectable so tests can drive
this without any real wall-clock waiting.
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.core.models import Bar


class _Window:
    """One instrument's in-progress bar. `open`/`high`/`low`/`close` stay
    None until a real tick lands in this window; `volume_last` tracks Kite's
    cumulative `volume_traded` (NOT a per-tick volume) so the flush step can
    compute a true delta against the previous window's final reading.
    """

    __slots__ = ("window_start", "open", "high", "low", "close", "volume_last")

    def __init__(self, window_start: float) -> None:
        self.window_start = window_start
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.volume_last: Optional[float] = None

    def update(self, tick: dict) -> None:
        price = tick["last_price"]
        if self.open is None:
            self.open = price
        self.high = price if self.high is None else max(self.high, price)
        self.low = price if self.low is None else min(self.low, price)
        self.close = price
        volume_traded = tick.get("volume_traded")
        if volume_traded is not None:
            self.volume_last = volume_traded


class TickBarAggregator:
    def __init__(
        self,
        timeframe: str = "1m",
        timeframe_seconds: float = 60.0,
        tick_check_seconds: float = 1.0,
        now_fn: Callable[[], float] = None,
        sleep_fn: Callable[[float], "asyncio.Future"] = asyncio.sleep,
    ) -> None:
        self._timeframe = timeframe
        self._timeframe_seconds = timeframe_seconds
        self._tick_check_seconds = tick_check_seconds
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc).timestamp())
        self._sleep_fn = sleep_fn

        self._windows: dict[int, _Window] = {}
        self._last_close: dict[int, float] = {}
        self._last_cum_volume: dict[int, float] = {}

    def _ingest(self, ticks: list[dict]) -> None:
        now = self._now_fn()
        for tick in ticks:
            token = tick["instrument_token"]
            window = self._windows.get(token)
            if window is None:
                window_start = now - (now % self._timeframe_seconds)
                window = self._windows[token] = _Window(window_start)
            window.update(tick)

    def _flush_due_windows(self, now: float) -> list:
        bars = []
        for token in set(self._windows.keys()) | set(self._last_close.keys()):
            window = self._windows.get(token)
            window_start = window.window_start if window is not None else None
            if window_start is None or now < window_start + self._timeframe_seconds:
                continue

            if window is not None and window.close is not None:
                volume = 0.0
                if window.volume_last is not None:
                    baseline = self._last_cum_volume.get(token)
                    volume = max(0.0, window.volume_last - baseline) if baseline is not None else 0.0
                    self._last_cum_volume[token] = window.volume_last
                bar = Bar(
                    instrument_token=token,
                    timeframe=self._timeframe,
                    timestamp=datetime.fromtimestamp(window.window_start, tz=timezone.utc),
                    open=window.open,
                    high=window.high,
                    low=window.low,
                    close=window.close,
                    volume=volume,
                )
                self._last_close[token] = window.close
            else:
                last_close = self._last_close.get(token)
                if last_close is None:
                    self._windows.pop(token, None)
                    continue
                bar = Bar(
                    instrument_token=token,
                    timeframe=self._timeframe,
                    timestamp=datetime.fromtimestamp(window_start, tz=timezone.utc),
                    open=last_close,
                    high=last_close,
                    low=last_close,
                    close=last_close,
                    volume=0.0,
                )

            next_start = window_start + self._timeframe_seconds
            self._windows[token] = _Window(next_start)
            bars.append((window_start, bar))

        bars.sort(key=lambda pair: pair[0])
        return [bar for _, bar in bars]
