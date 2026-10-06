from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.datalayer.news_sources import FEEDS
from backend.system import data_quality

NOW = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)


async def test_the_check_names_stale_bars_unlisted_symbols_and_silent_feeds():
    db = AsyncMongoMockClient()["test_db"]
    await db["daily_bars"].insert_many([
        {"symbol": "TCS", "date": "2026-10-06"}, {"symbol": "TCS", "date": "2026-10-05"},
        {"symbol": "INFY", "date": "2026-10-06"},
        {"symbol": "GMRINFRA", "date": "2026-09-25"},  # its quote stopped coming
    ])
    await db["user_prefs"].insert_one({"user_id": "alice", "universe": ["TCS.NS", "INFY", "OLDCO"]})
    await db["instruments"].insert_many([
        {"exchange": "NSE", "tradingsymbol": "TCS"}, {"exchange": "NSE", "tradingsymbol": "INFY"}])
    heard = [name for name, *_ in FEEDS][1:]
    await db["news_items"].insert_many([
        {"feeds": heard, "fetched_at": NOW - timedelta(hours=1)},
        {"feeds": [FEEDS[0][0]], "fetched_at": NOW - timedelta(days=4)},  # quiet for 4 days
    ])

    report = await data_quality.check(db, now=NOW)

    assert report["bars_as_of"] == "2026-10-06"
    assert report["stale_bars"] == 1 and report["stale"] == "GMRINFRA"
    assert report["unlisted_in_universes"] == 1 and report["unlisted"] == "OLDCO"
    assert report["silent_feeds"] == 1 and report["silent"] == FEEDS[0][0]
