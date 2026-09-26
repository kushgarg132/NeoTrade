"""Turning a signal's quality into Intent.strength. Pure math, no I/O.

Strategies used to emit one constant strength each (breakout 0.8, MACD 0.75,
mean reversion 0.7), so conviction ranked which strategy fired, never how
good the setup was. Now each strategy keeps its entry rules unchanged and
grades the setup into a range; the bottom of every range stays above
backend.scoring.composite.RULE_FLOOR, so grading never suppresses a signal
that used to reach the inbox.
"""

import math
from typing import Optional


def ramp(value: Optional[float], start: float, full: float) -> float:
    """0 at `start`, 1 at `full`, linear between, clamped. Unknown (None or
    NaN) is 0.5 -- missing data neither helps nor hurts a setup."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.5
    if full == start:
        return 1.0 if value >= full else 0.0
    return max(0.0, min(1.0, (value - start) / (full - start)))


def graded(low: float, high: float, *factors: float) -> float:
    """Maps the mean of 0..1 quality factors onto [low, high]."""
    quality = sum(factors) / len(factors)
    return round(low + (high - low) * quality, 4)


def sma(values: list[float], n: int) -> Optional[float]:
    return sum(values[-n:]) / n if len(values) >= n else None
