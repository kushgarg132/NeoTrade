"""Jobs record their last run in Redis (job:last:<name>) for the handbook's
live panels; recording must never break the job itself."""

import asyncio

import pytest

from backend import scheduler
from backend.system.jobs import DAILY_PASS, last_runs, mark
from backend.tests.test_datalayer_news import FakeRedis


def test_mark_writes_the_record():
    redis = FakeRedis()
    asyncio.run(mark(redis, "autorun", True, "started 1"))
    run = asyncio.run(last_runs(redis, ["autorun"]))["autorun"]
    assert run["ok"] is True and run["note"] == "started 1" and run["at"].endswith("+00:00")


def test_last_runs_missing_is_none():
    assert asyncio.run(last_runs(FakeRedis(), ["telegram"])) == {"telegram": None}


def test_mark_failure_never_breaks_the_job():
    class Broken(FakeRedis):
        async def hset(self, key, mapping):
            raise ConnectionError("redis down")

    assert asyncio.run(mark(Broken(), "autorun", True)) is None


def test_daily_pass_records_success_and_failure(monkeypatch):
    redis = FakeRedis()

    async def ok(db, redis=None, now=None):
        return {"created": 2}

    monkeypatch.setattr(scheduler, "run_daily_jobs", ok)
    asyncio.run(scheduler._run_locked(None, redis))
    run = asyncio.run(last_runs(redis, [DAILY_PASS]))[DAILY_PASS]
    assert run["ok"] is True and '"created": 2' in run["note"]

    async def boom(db, redis=None, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "run_daily_jobs", boom)
    asyncio.run(redis.delete(scheduler.LAST_PASS_KEY))  # the ok run counted for today
    with pytest.raises(RuntimeError):
        asyncio.run(scheduler._run_locked(None, redis))
    run = asyncio.run(last_runs(redis, [DAILY_PASS]))[DAILY_PASS]
    assert run["ok"] is False and "boom" in run["note"]
