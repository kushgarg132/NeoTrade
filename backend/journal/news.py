"""What the news said about a stock around a journal trip: the strongest
scored impact on its underlying in the 24 hours before ENTRY (`news`) and
before EXIT (`exit_news`). An exit item also carries `after_5d_pct`: the
underlying's move over the 5 stored daily bars after the exit day (None
without the bars). Attached at read time (journal trips come from broker sync,
not the engine ledger), for the news findings in insights.py and the chips in
the journal."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import timedelta, timezone

import pandas as pd

from backend.engine.session import IST

WINDOW = timedelta(hours=24)
AFTER_BARS = 5


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _naive_utc(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _after_pct(frame, day) -> float | None:
    """% from the close on (or last before) `day` to the close AFTER_BARS bars later."""
    if frame is None:
        return None
    closes = frame["close"]
    at = closes.index.searchsorted(pd.Timestamp(day), side="right") - 1
    if at < 0 or at + AFTER_BARS >= len(closes):
        return None
    base = float(closes.iloc[at])
    return round((float(closes.iloc[at + AFTER_BARS]) / base - 1) * 100, 2) if base else None


async def attach_news(db, trips: list[dict]) -> list[dict]:
    if not trips:
        return trips
    names = {t.get("underlying") or t["symbol"] for t in trips}
    moments = [_aware(t["opened_at"]) for t in trips] + [_aware(t["closed_at"]) for t in trips if t.get("closed_at")]
    docs = await db["news_items"].find(
        {"status": "SCORED", "impacts.target": {"$in": sorted(names)},
         "published_at": {"$gte": _naive_utc(min(moments) - WINDOW), "$lte": _naive_utc(max(moments))}},
        {"published_at": 1, "impacts": 1, "title": 1, "url": 1},
    ).to_list(length=None)
    # Per symbol, its impacts sorted by time: each moment bisects its own 24h window.
    by_name: dict[str, list[tuple]] = defaultdict(list)
    for doc in docs:
        at = _aware(doc["published_at"])
        for i in doc.get("impacts") or []:
            if i.get("type") == "symbol" and i.get("target") in names:
                by_name[i["target"]].append((at, i["impact"], i["direction"], doc.get("title"), doc.get("url")))
    for rows in by_name.values():
        rows.sort(key=lambda r: r[0])
    times = {name: [r[0] for r in rows] for name, rows in by_name.items()}

    def strongest(name, moment):
        if moment is None:
            return None
        moment = _aware(moment)
        lo, hi = bisect_left(times.get(name, []), moment - WINDOW), bisect_right(times.get(name, []), moment)
        best = max(by_name.get(name, [])[lo:hi], key=lambda r: r[1], default=None)
        return ({"direction": best[2], "impact": best[1], "headline": best[3], "url": best[4],
                 "minutes_before": int((moment - best[0]).total_seconds() // 60)} if best else None)

    for trip in trips:
        name = trip.get("underlying") or trip["symbol"]
        trip["news"] = strongest(name, trip["opened_at"])
        trip["exit_news"] = strongest(name, trip.get("closed_at"))

    exits = [t for t in trips if t["exit_news"]]
    if exits:
        from backend.datalayer.bars import read

        first = min(_aware(t["closed_at"]).astimezone(IST).date() for t in exits)
        frames = await read(db, {t.get("underlying") or t["symbol"] for t in exits}, first - timedelta(days=7))
        for t in exits:
            t["exit_news"]["after_5d_pct"] = _after_pct(frames.get(t.get("underlying") or t["symbol"]),
                                                        _aware(t["closed_at"]).astimezone(IST).date())
    return trips
