"""Per-symbol daily-bar indicator state for swing blocks: one update per trading day.

SMA / ATR / RSI 2 mirror components/quant/indicators.py (same seeding), so a block
reading it agrees with the batch indicators. Pure: no I/O, no clock.
"""
from collections import deque

from backend.core.models import Bar

_SMAS = (10, 20, 50, 100, 200)
_KEEP = 256  # longest look-back (200-day SMA, 126-day return) plus today and slack


class SwingState:
    def __init__(self):
        self._c, self._h, self._l = (deque(maxlen=_KEEP) for _ in range(3))
        self._tr = deque(maxlen=14)
        self._vols = deque(maxlen=20)  # volumes of days before the current one
        self._turn = deque(maxlen=20)  # close x volume, including the current day
        self._rsi_avg = None  # (avg_gain, avg_loss), Wilder alpha 1/2
        self.bars = 0
        self.open = self.close = self.high = self.low = self.volume = None
        self.prev_close = self.prev_high = self.prev_low = None
        self.atr = self.rsi2 = self.vol_avg20 = self.turnover_avg20 = None

    def update(self, bar: Bar) -> None:
        self.prev_close, self.prev_high, self.prev_low = self.close, self.high, self.low
        self.open, self.high, self.low, self.close, self.volume = bar.open, bar.high, bar.low, bar.close, bar.volume
        self.bars += 1

        tr = bar.high - bar.low
        if self.prev_close is not None:
            tr = max(tr, abs(bar.high - self.prev_close), abs(bar.low - self.prev_close))
        self._tr.append(tr)
        self.atr = sum(self._tr) / 14 if len(self._tr) == 14 else None

        self.vol_avg20 = sum(self._vols) / 20 if len(self._vols) == 20 else None
        self._vols.append(bar.volume)
        self._turn.append(bar.close * bar.volume)
        self.turnover_avg20 = sum(self._turn) / 20 if len(self._turn) == 20 else None

        delta = bar.close - self.prev_close if self.prev_close is not None else 0.0
        g, l = max(delta, 0.0), max(-delta, 0.0)
        a = self._rsi_avg
        a = (g, l) if a is None else (a[0] + (g - a[0]) / 2, a[1] + (l - a[1]) / 2)
        self._rsi_avg = a
        self.rsi2 = 100 - 100 / (1 + a[0] / a[1]) if a[1] else (100.0 if a[0] else None)

        self._c.append(bar.close)
        self._h.append(bar.high)
        self._l.append(bar.low)

    def sma(self, n: int) -> float | None:
        if len(self._c) < n:
            return None
        return sum(list(self._c)[-n:]) / n

    def high_n(self, n: int) -> float | None:
        """Highest high of the n bars before today."""
        return max(list(self._h)[-n - 1:-1]) if len(self._h) > n else None

    def low_n(self, n: int) -> float | None:
        """Lowest low of the n bars before today."""
        return min(list(self._l)[-n - 1:-1]) if len(self._l) > n else None

    def ret(self, n: int, ago: int = 0) -> float | None:
        """n-day return as of `ago` bars back (0 = today's close)."""
        return self._c[-1 - ago] / self._c[-n - 1 - ago] - 1 if len(self._c) > n + ago else None
