"""Overnight news catalysts per trading day, for strategies that trade gaps
(backend/strategies/intraday/gap_and_go.py, gap_fill_fade.py).

A catalyst for day D is a material scored impact on a symbol published
between the previous weekday's close (15:30 IST) and D's open (09:15 IST).
The strongest impact per symbol wins; its direction (-1..1) is the value.
Strategies get the map at construction, so they stay I/O-free.
"""

from datetime import date, datetime, time, timedelta, timezone

from backend.engine.session import IST
from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

CLOSE, OPEN = time(15, 30), time(9, 15)


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _window(day: date) -> tuple[datetime, datetime]:
    prev = day - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return datetime.combine(prev, CLOSE, IST), datetime.combine(day, OPEN, IST)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def catalyst_map(db, start: date, end: date) -> dict[str, dict[str, float]]:
    days = _weekdays(start, end)
    result: dict[str, dict[str, float]] = {d.isoformat(): {} for d in days}
    if not days:
        return result
    windows = [(d.isoformat(), *_window(d)) for d in days]
    lo, hi = windows[0][1], windows[-1][2]
    docs = await db["news_items"].find(
        {"status": "SCORED", "impacts.type": "symbol",
         "published_at": {"$gte": lo.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
                          "$lt": hi.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(days=1)}},
        {"published_at": 1, "impacts": 1},
    ).to_list(length=None)
    best: dict[tuple[str, str], tuple[float, float]] = {}
    for doc in docs:
        at = _utc(doc["published_at"])
        day = next((key for key, a, b in windows if a <= at < b), None)
        if day is None:
            continue
        for i in doc.get("impacts") or []:
            if i.get("type") != "symbol" or i.get("impact", 0) < MATERIALITY_THRESHOLD:
                continue
            key = (day, i["target"])
            if key not in best or i["impact"] > best[key][0]:
                best[key] = (i["impact"], i["direction"])
    for (day, symbol), (_, direction) in best.items():
        result[day][symbol] = direction
    return result
