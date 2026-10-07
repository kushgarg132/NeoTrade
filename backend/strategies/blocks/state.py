"""Incremental per-symbol indicator state: one O(1) update per bar.

Every value mirrors components/quant/indicators.py (same seeding), so a block
reading it agrees with the batch indicators and the backtester. Pure: no I/O,
no clock.
"""
from collections import deque
from datetime import timedelta

from backend.core.models import Bar
from backend.engine.session import IST


class SymbolState:
    def __init__(self, ema_periods: set[int], rsi_periods: set[int], range_minutes: set[int]):
        self._ema = {p: None for p in ema_periods}
        self._rsi_p = rsi_periods
        self._avg = {p: None for p in rsi_periods}  # (avg_gain, avg_loss)
        self._rsi = {p: None for p in rsi_periods}
        self._prev_rsi = {p: None for p in rsi_periods}
        self._range_minutes = range_minutes
        self._tr = deque(maxlen=14)
        self._vols = deque(maxlen=20)  # volumes of bars before the current one
        self._range_bars: list[Bar] = []
        self.last_bar: Bar | None = None
        self.prev_bar: Bar | None = None
        self.day = None
        self.bars_today = 0
        self.open = self.close = None
        self.prev_close = None
        self.vwap = self.prev_vwap = None
        self.atr = None
        self.vol_avg20 = None
        self._pv = self._vol = 0.0
        self._first_ts = None
        self._step = None

    def update(self, bar: Bar, prev_close: float | None = None) -> None:
        last = self.last_bar
        day = bar.timestamp.astimezone(IST).date()
        if day != self.day:
            self.prev_close = last.close if last else None
            self.day, self.bars_today, self.open = day, 0, bar.open
            self._pv = self._vol = 0.0
            self.vwap = None
            self._range_bars, self._first_ts, self._step = [], bar.timestamp, None
        if prev_close is not None and self.bars_today == 0:
            self.prev_close = prev_close
        elif self.bars_today == 1 and self._step is None:
            self._step = bar.timestamp - self._first_ts
        self.prev_bar, self.last_bar = last, bar
        self.bars_today += 1
        self.close = bar.close

        # ATR is a plain 14-bar mean of true range (as the batch indicator), TR spans sessions.
        tr = bar.high - bar.low
        if last:
            tr = max(tr, abs(bar.high - last.close), abs(bar.low - last.close))
        self._tr.append(tr)
        self.atr = sum(self._tr) / 14 if len(self._tr) == 14 else None

        self.vol_avg20 = sum(self._vols) / 20 if len(self._vols) == 20 else None
        self._vols.append(bar.volume)

        self.prev_vwap = self.vwap
        self._pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
        self._vol += bar.volume
        self.vwap = self._pv / self._vol if self._vol else None

        for p, v in self._ema.items():
            self._ema[p] = bar.close if v is None else v + (bar.close - v) * 2 / (p + 1)

        delta = bar.close - last.close if last else 0.0
        for p in self._rsi_p:
            g, l = max(delta, 0.0), max(-delta, 0.0)
            a = self._avg[p]
            a = (g, l) if a is None else (a[0] + (g - a[0]) / p, a[1] + (l - a[1]) / p)
            self._avg[p] = a
            self._prev_rsi[p] = self._rsi[p]
            if a[1]:
                self._rsi[p] = 100 - 100 / (1 + a[0] / a[1])
            else:
                self._rsi[p] = 100.0 if a[0] else None

        if self._range_minutes and bar.timestamp - self._first_ts < max(self._range_minutes) * _MIN:
            self._range_bars.append(bar)

    def ema(self, period: int) -> float | None:
        return self._ema[period]

    def rsi(self, period: int) -> float | None:
        return self._rsi[period]

    def prev_rsi(self, period: int) -> float | None:
        return self._prev_rsi[period]

    def _range(self, minutes: int, fn) -> float | None:
        """Opening range of the first `minutes`; None until a bar has covered it."""
        end = self._first_ts + minutes * _MIN
        bars = [b for b in self._range_bars if b.timestamp < end]
        last = self.last_bar.timestamp
        # Complete once a later bar arrived, or the last bar's end (ts + bar step) reaches `end`.
        if last < end and not (self._step and last + self._step >= end):
            return None
        return fn(bars)

    def range_high(self, minutes: int) -> float | None:
        return self._range(minutes, lambda bs: max(b.high for b in bs))

    def range_low(self, minutes: int) -> float | None:
        return self._range(minutes, lambda bs: min(b.low for b in bs))



_MIN = timedelta(minutes=1)
