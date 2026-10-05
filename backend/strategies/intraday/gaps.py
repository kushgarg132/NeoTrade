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


def previous_close(today: list[Bar], prior: list[Bar], prev_closes: dict[str, dict[str, float]],
                   symbol: str) -> Optional[float]:
    """The prior session's last close from the bars when history has it
    (backtests), else from `prev_closes` ({date_iso: {symbol: close}},
    handed in at construction): live feeds carry only today's bars."""
    if prior:
        return prior[-1].close
    if not today:
        return None
    return prev_closes.get(today[0].timestamp.date().isoformat(), {}).get(symbol)


def gap_pct(today: list[Bar], prev_close: Optional[float]) -> Optional[float]:
    if not today or not prev_close:
        return None
    return (today[0].open / prev_close - 1) * 100


def opening_range(today: list[Bar], minutes: int) -> tuple[list[Bar], list[Bar]]:
    """(bars inside the first `minutes`, bars after it)."""
    end = today[0].timestamp + timedelta(minutes=minutes)
    return [b for b in today if b.timestamp < end], [b for b in today if b.timestamp >= end]
