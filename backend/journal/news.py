"""What the news said about a stock when a journal trip opened: the
strongest scored impact on its underlying in the 24 hours before entry.
Attached at read time (journal trips come from broker sync, not the engine
ledger), for the news findings in insights.py."""

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
         "published_at": {"$gte": (min(opens) - WINDOW).replace(tzinfo=None),
                          "$lte": max(opens).replace(tzinfo=None)}},
        {"published_at": 1, "impacts": 1},
    ).to_list(length=None)
    for trip in trips:
        name, opened = trip.get("underlying") or trip["symbol"], _aware(trip["opened_at"])
        best = None
        for doc in docs:
            at = _aware(doc["published_at"])
            if not (opened - WINDOW <= at <= opened):
                continue
            for i in doc.get("impacts") or []:
                if i.get("type") == "symbol" and i.get("target") == name and (best is None or i["impact"] > best[0]):
                    best = (i["impact"], i["direction"], int((opened - at).total_seconds() // 60))
        trip["news"] = {"direction": best[1], "impact": best[0], "minutes_before": best[2]} if best else None
    return trips
