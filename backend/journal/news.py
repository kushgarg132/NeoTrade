"""What the news said about a stock when a journal trip opened: the
strongest scored impact on its underlying in the 24 hours before entry.
Attached at read time (journal trips come from broker sync, not the engine
ledger), for the news findings in insights.py."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import timedelta, timezone

WINDOW = timedelta(hours=24)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def attach_news(db, trips: list[dict]) -> list[dict]:
    if not trips:
        return trips
    names = {t.get("underlying") or t["symbol"] for t in trips}
    opens = [_aware(t["opened_at"]) for t in trips]
    docs = await db["news_items"].find(
        {"status": "SCORED", "impacts.target": {"$in": sorted(names)},
         "published_at": {"$gte": (min(opens) - WINDOW).astimezone(timezone.utc).replace(tzinfo=None),
                          "$lte": max(opens).astimezone(timezone.utc).replace(tzinfo=None)}},
        {"published_at": 1, "impacts": 1},
    ).to_list(length=None)
    # Per symbol, its impacts sorted by time: each trip bisects its own 24h window.
    by_name: dict[str, list[tuple]] = defaultdict(list)
    for doc in docs:
        at = _aware(doc["published_at"])
        for i in doc.get("impacts") or []:
            if i.get("type") == "symbol" and i.get("target") in names:
                by_name[i["target"]].append((at, i["impact"], i["direction"]))
    for rows in by_name.values():
        rows.sort(key=lambda r: r[0])
    times = {name: [r[0] for r in rows] for name, rows in by_name.items()}
    for trip, opened in zip(trips, opens):
        name = trip.get("underlying") or trip["symbol"]
        rows = by_name.get(name, [])
        lo, hi = bisect_left(times.get(name, []), opened - WINDOW), bisect_right(times.get(name, []), opened)
        best = max(rows[lo:hi], key=lambda r: r[1], default=None)
        trip["news"] = ({"direction": best[2], "impact": best[1],
                         "minutes_before": int((opened - best[0]).total_seconds() // 60)} if best else None)
    return trips
