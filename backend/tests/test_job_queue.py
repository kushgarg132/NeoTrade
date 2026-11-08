"""Manual runs go to the jobs process when it is alive, else run in the API."""

import asyncio
import json
import time

import pytest

from backend import job_queue


class FakeRedis:
    def __init__(self, beat_age: int | None = None):
        self.lists: dict[str, list[str]] = {}
        self.beat = None if beat_age is None else str(int(time.time()) - beat_age)

    async def get(self, key):
        return self.beat if key == "jobs:heartbeat" else None

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def brpop(self, key, timeout=0):
        items = self.lists.get(key) or []
        return (key, items.pop()) if items else None


@pytest.fixture
def ran(monkeypatch):
    calls = []

    async def fake_scan(db, redis, user_id, universe):
        calls.append(("scan", user_id, universe))

    async def boom(db, redis, **args):
        raise RuntimeError("boom")

    monkeypatch.setattr(job_queue, "KINDS", {"scan": fake_scan, "boom": boom})
    return calls


@pytest.mark.asyncio
async def test_alive_jobs_process_gets_the_run(ran):
    redis = FakeRedis(beat_age=5)
    assert await job_queue.submit(None, redis, "scan", user_id="u", universe=["ITC"]) == "queued"
    await asyncio.sleep(0)
    assert ran == []
    assert json.loads(redis.lists[job_queue.KEY][0]) == {"kind": "scan", "args": {"user_id": "u", "universe": ["ITC"]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("redis", [None, FakeRedis(), FakeRedis(beat_age=600)])
async def test_no_live_jobs_process_runs_here(ran, redis):
    assert await job_queue.submit(None, redis, "scan", user_id="u", universe=["ITC"]) == "local"
    await asyncio.sleep(0)
    assert ran == [("scan", "u", ["ITC"])]


@pytest.mark.asyncio
async def test_worker_runs_queued_items_and_survives_bad_ones(ran):
    redis = FakeRedis(beat_age=5)
    for kind in ("boom", "nope", "scan"):
        await job_queue.submit(None, redis, kind, **({"user_id": "u", "universe": []} if kind == "scan" else {}))
    for _ in range(3):
        await job_queue.work_once(None, redis)
    await asyncio.sleep(0)
    assert ran == [("scan", "u", [])]
    assert await job_queue.work_once(None, redis) is False  # empty queue
