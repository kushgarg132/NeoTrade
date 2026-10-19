"""NSE equity (cash market) trading calendar: weekends plus a static holiday set.

2026 is NSE's official list (CM segment, as served by
https://www.nseindia.com/api/holiday-master?type=trading, the data behind
https://www.nseindia.com/resources/exchange-communication-holidays). It includes
15-Jan-2026 (Municipal Corporation Election, Maharashtra), a weekday closure
that some broker pages omit. Weekend-only holidays are not listed.

2027 is PROVISIONAL: NSE had not published its 2027 circular when this was
written. Only weekday dates fixed by the Gregorian or well-known religious
calendar are listed; lunar ones that may move by a day (Dussehra, Mahavir
Jayanti, Guru Nanak Jayanti) are left out on purpose, because a wrongly listed
holiday skips a real session while a missing one only keeps today's behaviour.
Replace this set with the official circular when NSE publishes it.
"""
from datetime import date, timedelta

HOLIDAYS = frozenset(date.fromisoformat(d) for d in (
    # 2026, official
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
    # 2027, provisional
    "2027-01-26", "2027-03-10", "2027-03-22", "2027-03-26", "2027-04-14", "2027-04-15",
    "2027-05-17", "2027-06-16", "2027-10-29",
))


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def previous_trading_day(day: date) -> date:
    """The trading day strictly before `day`."""
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def next_trading_day(day: date) -> date:
    """The trading day strictly after `day`."""
    day += timedelta(days=1)
    while not is_trading_day(day):
        day += timedelta(days=1)
    return day


def last_trading_day(day: date) -> date:
    """`day` itself if it trades, else the one before."""
    return day if is_trading_day(day) else previous_trading_day(day)


def add_trading_days(day: date, n: int) -> date:
    for _ in range(n):
        day = next_trading_day(day)
    return day


def trading_days_between(a: date, b: date) -> list[date]:
    """Trading days from `a` to `b`, both inclusive."""
    days = (a + timedelta(days=i) for i in range((b - a).days + 1))
    return [d for d in days if is_trading_day(d)]


def is_last_trading_day_of_week(day: date) -> bool:
    return is_trading_day(day) and next_trading_day(day).isocalendar()[:2] != day.isocalendar()[:2]
