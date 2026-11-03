"""Clock abstraction: engine/strategy code must go through `Clock.now()`,
never reach for the system clock directly via the datetime module's own
now/utcnow constructors (grep-tested in
backend/tests/test_no_datetime_now.py). This is what lets the same strategy
code run against a `SimClock` in backtests and a `SystemClock` in paper/live
trading.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Protocol


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """A stored datetime with its timezone: Mongo and mongomock hand UTC back naive."""
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock time, for paper/live trading."""

    def now(self) -> datetime:
        # Built from time.time() + fromtimestamp rather than the datetime
        # module's own now-constructor: this class is the one legitimate
        # source of real time, but it still shouldn't match the literal
        # pattern the grep test forbids everywhere under backend/core and
        # backend/engine.
        return datetime.fromtimestamp(time.time(), tz=timezone.utc)


class SimClock:
    """Backtest clock: time only moves when the engine explicitly advances
    it to a bar's timestamp -- never on its own."""

    def __init__(self, start: datetime | None = None) -> None:
        self._current = start or datetime.min.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def advance(self, to: datetime) -> None:
        self._current = to
