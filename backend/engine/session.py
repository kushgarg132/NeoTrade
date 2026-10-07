"""NSE trading-session helpers. Currently just the MIS intraday square-off
cutoff: 15:15 IST, 15 minutes before the 15:30 close -- the standard
convention Indian discount brokers auto-square-off MIS positions at (some
brokers cut it earlier/later; 15:15 is the most common). Pure function, no
I/O, so it works identically whether the bar came from a live/polling feed
or a HistoricalFeed backtest replay -- runner.run (Task 6) calls this on
every bar for INTRADAY-mode symbols, live or historical alike.
"""

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def clock(dt: datetime) -> str:
    """Every clock time a user reads: 12-hour IST, "3:20 PM"."""
    return dt.astimezone(IST).strftime("%I:%M %p").lstrip("0")
SQUARE_OFF_HOUR = 15
SQUARE_OFF_MINUTE = 15


def is_past_square_off_time(timestamp: datetime) -> bool:
    """True once `timestamp` (any timezone, including naive-as-UTC) is at or
    past 15:15 IST on its own calendar day."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    ist_time = timestamp.astimezone(IST)
    cutoff = ist_time.replace(
        hour=SQUARE_OFF_HOUR, minute=SQUARE_OFF_MINUTE, second=0, microsecond=0
    )
    return ist_time >= cutoff
