import asyncio

from backend import locks
from backend.datalayer import worker


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, nx=False, xx=False, px=None, ex=None):
        if (nx and key in self.data) or (xx and key not in self.data):
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix):
                yield key


async def test_lock_only_holder_renews_or_releases():
    redis = FakeRedis()
    token = await locks.acquire(redis, "k", 1000)
    assert token and await locks.acquire(redis, "k", 1000) is None
    assert not await locks.renew(redis, "k", "other", 1000)
    await locks.release(redis, "k", "other")
    assert redis.data["k"] == token
    assert await locks.renew(redis, "k", token, 1000)
    await locks.release(redis, "k", token)
    assert "k" not in redis.data


async def test_leader_runs_loops_and_beats(monkeypatch):
    monkeypatch.setattr(worker, "RENEW_SECONDS", 0.01)
    redis, calls = FakeRedis(), []

    async def tick(db, r):
        calls.append(1)

    task = asyncio.create_task(worker.run(None, redis, [worker.Loop("quotes", 0.01, tick)]))
    await asyncio.sleep(0.05)
    assert calls
    assert set(await worker.heartbeat_ages(redis)) == {"leader", "quotes"}

    redis.data[worker.LEADER_KEY] = "stolen"  # another instance took over
    await asyncio.wait_for(task, 1)
    assert redis.data[worker.LEADER_KEY] == "stolen"  # never deletes someone else's lock


async def test_second_instance_waits_for_the_lock(monkeypatch):
    monkeypatch.setattr(worker, "RENEW_SECONDS", 0.01)
    redis, calls = FakeRedis(), []
    redis.data[worker.LEADER_KEY] = "held"

    async def tick(db, r):
        calls.append(1)

    task = asyncio.create_task(worker.run(None, redis, [worker.Loop("quotes", 0.01, tick)]))
    await asyncio.sleep(0.05)
    assert not calls
    del redis.data[worker.LEADER_KEY]
    await asyncio.sleep(0.05)
    assert calls
    task.cancel()


async def test_a_failing_loop_does_not_beat(monkeypatch):
    redis = FakeRedis()

    async def boom(db, r):
        raise RuntimeError("source down")

    task = asyncio.create_task(worker._run_loop(None, redis, worker.Loop("news", 0.01, boom)))
    await asyncio.sleep(0.03)
    assert not task.done()  # kept running instead of raising out
    task.cancel()
    assert "news" not in await worker.heartbeat_ages(redis)
