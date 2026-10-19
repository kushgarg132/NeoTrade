import json
import time
from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.datalayer.news_sources import FEEDS
from backend.datalayer.worker import RENEW_SECONDS, _loops
from backend.factor.data import universe
from backend.system import data_quality

NOW = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)  # Wednesday 16:30 IST
MONDAY_MORNING = datetime(2026, 10, 19, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
SATURDAY = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)


class _Redis:
    def __init__(self, **values):
        self.values = dict(values)
        self.hashes = {}

    async def get(self, key):
        return self.values.get(key)

    async def mget(self, keys):
        return [self.values.get(k) for k in keys]

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key

    async def hgetall(self, key):
        return self.hashes.get(key, {})


def _healthy(**overrides) -> _Redis:
    """Every ingest loop just beat, quotes are cached, Friday's pass ran."""
    now = int(time.time())
    values = {f"ingest:heartbeat:{loop.name}": str(now - 5) for loop in _loops()}
    values["ingest:heartbeat:leader"] = str(now - 1)
    values[f"quote:{universe()[0]}"] = json.dumps({"ltp": 1.0})
    values["scheduler:last_pass"] = "2026-10-16"
    values.update(overrides)
    return _Redis(**{k: v for k, v in values.items() if v is not None})


async def _picks_ran(db, at):
    await db["picks_study"].insert_one({"_id": "latest", "as_of": at})


async def test_the_check_names_stale_bars_unlisted_symbols_and_silent_feeds():
    db = AsyncMongoMockClient()["test_db"]
    await db["daily_bars"].insert_many([
        {"symbol": "TCS", "date": "2026-10-07"}, {"symbol": "TCS", "date": "2026-10-06"},
        {"symbol": "INFY", "date": "2026-10-07"},
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

    assert report["bars_as_of"] == "2026-10-07"
    assert report["stale_bars"] == 1 and report["stale"] == "GMRINFRA"
    assert report["unlisted_in_universes"] == 1 and report["unlisted"] == "OLDCO"
    assert report["silent_feeds"] == 1 and report["silent"] == FEEDS[0][0]
    assert report["failures"][0].startswith("Stale bars: 1 symbol(s) behind 2026-10-07")


async def test_every_stock_a_day_late_is_stale_even_when_nifty_is_current():
    """2026-10-15: Upstox history ended at yesterday, so each stock's newest bar was a day late."""
    db = AsyncMongoMockClient()["test_db"]
    await db["daily_bars"].insert_many([
        {"symbol": "TCS", "date": "2026-10-06"}, {"symbol": "INFY", "date": "2026-10-06"},
        {"symbol": "^NSEI", "date": "2026-10-07"},
    ])
    report = await data_quality.check(db, now=NOW)
    assert report["stale_bars"] == 2 and report["stale"] == "INFY, TCS"
    # Before 15:45 IST the day's bars are not due yet.
    early = await data_quality.check(db, now=NOW.replace(hour=9))
    assert early["stale_bars"] == 0


async def test_a_healthy_system_has_no_live_failures():
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 16, 10, 35, tzinfo=timezone.utc))
    assert await data_quality.live(db, _healthy(), MONDAY_MORNING) == []


async def test_a_dead_or_slow_ingest_loop_is_named():
    """2026-10-15: the ingest worker sat idle for 44 hours and nothing said so."""
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 16, 10, 35, tzinfo=timezone.utc))
    now = int(time.time())
    redis = _healthy(**{"ingest:heartbeat:news_poll": str(now - 600),  # a 60 s loop, 10 min quiet
                        "ingest:heartbeat:bars": str(now - 1000),      # a 15 min loop: still within 2x
                        "ingest:heartbeat:calendar": None})            # key expired: dead
    failures = await data_quality.live(db, redis, MONDAY_MORNING)
    assert failures == ["Ingest loop news_poll last beat 10 min ago",
                        "Ingest loop calendar has not beaten recently (heartbeat expired)"]
    assert RENEW_SECONDS < data_quality.MIN_STALE_SECONDS  # the leader's 10 s beat never flaps


async def test_a_failing_quotes_loop_is_named():
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 16, 10, 35, tzinfo=timezone.utc))
    failures = await data_quality.live(db, _healthy(**{f"quote:{universe()[0]}": None}), MONDAY_MORNING)
    assert len(failures) == 1 and failures[0].startswith("Quotes loop failing")


async def test_a_missed_daily_pass_and_picks_run_are_named_by_the_last_weekday():
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 15, 10, 35, tzinfo=timezone.utc))  # Thursday's
    failures = await data_quality.live(db, _healthy(**{"scheduler:last_pass": "2026-10-15"}), MONDAY_MORNING)
    assert failures == ["Daily pass for 2026-10-16 has not run (last: 2026-10-15)",
                        "Picks job has not run for 2026-10-16 (last: 2026-10-15)"]
    # Friday's runs satisfy Saturday and Sunday: the weekend is not a gap.
    assert data_quality.last_trading_day_at(SATURDAY, data_quality.PASS_DONE).isoformat() == "2026-10-16"


async def test_admin_alerts_add_the_nightly_stale_bars_and_stay_quiet_at_weekends():
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 16, 10, 35, tzinfo=timezone.utc))
    redis = _healthy()
    redis.hashes["job:last:data_quality"] = {
        "at": "2026-10-16T10:40:00+00:00", "ok": "0",
        "note": json.dumps({"failures": ["Stale bars: 2 symbol(s) behind 2026-10-16 (INFY, TCS)"]})}
    assert await data_quality.alerts(db, redis, MONDAY_MORNING) == [
        "Stale bars: 2 symbol(s) behind 2026-10-16 (INFY, TCS)"]
    redis.values.pop("scheduler:last_pass")
    assert await data_quality.alerts(db, redis, SATURDAY) == []
