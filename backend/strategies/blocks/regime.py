"""Market regime by day, shared by live runs and backtests so a `regime_is`
spec trades the same way in both. Pure: no I/O, no clock."""
from bisect import bisect_left
from datetime import date
from typing import Callable, Optional

WINDOW = 200


def regime_by_day(nifty: list[tuple[date, float]]) -> Callable[[date], Optional[str]]:
    """The Nifty's previous close above its 200-day average -> risk_on, below -> risk_off,
    fewer than 200 closes -> None. `neutral` is never produced."""
    rows = sorted(nifty)
    days = [d for d, _ in rows]
    closes = [c for _, c in rows]
    prefix = [0.0]
    for c in closes:
        prefix.append(prefix[-1] + c)

    def regime_of(day: date) -> Optional[str]:
        i = bisect_left(days, day) - 1  # last close strictly before `day`
        if i < WINDOW - 1:
            return None
        avg = (prefix[i + 1] - prefix[i + 1 - WINDOW]) / WINDOW
        return "risk_on" if closes[i] > avg else "risk_off"

    return regime_of
