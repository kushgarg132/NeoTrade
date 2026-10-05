"""Shared session helpers for the gap strategies (gap_and_go.py,
gap_fill_fade.py). Pure functions over a symbol's bar history."""

from datetime import timedelta
from typing import Optional

from backend.core.models import Bar

# Today's session (75 five-minute bars) plus the previous one, for its close.
SESSION_LOOKBACK_BARS = 160


def split_sessions(history: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    """(today's bars, the previous session's bars); the second is [] when
    history starts today."""
    if not history:
        return [], []
    today = history[-1].timestamp.date()
    current = [b for b in history if b.timestamp.date() == today]
    earlier = [b for b in history if b.timestamp.date() < today]
    if not earlier:
        return current, []
    last = earlier[-1].timestamp.date()
    return current, [b for b in earlier if b.timestamp.date() == last]


def gap_pct(today: list[Bar], prior: list[Bar]) -> Optional[float]:
    if not today or not prior or not prior[-1].close:
        return None
    return (today[0].open / prior[-1].close - 1) * 100


def opening_range(today: list[Bar], minutes: int) -> tuple[list[Bar], list[Bar]]:
    """(bars inside the first `minutes`, bars after it)."""
    end = today[0].timestamp + timedelta(minutes=minutes)
    return [b for b in today if b.timestamp < end], [b for b in today if b.timestamp >= end]
