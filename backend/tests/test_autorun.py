"""The daily intraday paper run starts itself at the open, exactly once
across workers, comes back after a deploy, respects a manual stop, and
stops at the close."""

import asyncio
from datetime import datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine import autorun
from backend.engine.session import IST
from backend.routers import trading
from backend.runs import RunStore

MONDAY_10AM = datetime(2026, 9, 28, 10, 0, tzinfo=IST)
MONDAY_EVENING = datetime(2026, 9, 28, 15, 31, tzinfo=IST)
SUNDAY_10AM = datetime(2026, 9, 27, 10, 0, tzinfo=IST)


class _Redis:
    """The three calls autorun makes, with NX/XX semantics (TTL ignored)."""

    def __init__(self):
        self.data = {}

    async def set(self, key, value, nx=False, xx=False, px=None):
        if (nx and key in self.data) or (xx and key not in self.data):
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


async def _forever():
    await asyncio.Event().wait()


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(autorun, "_LOCAL", {})
    monkeypatch.setattr(autorun, "_TOKEN", "worker-a")
    launched = []

    async def launch(user_id, mode, universe, poll, runs, origin):
        run_id = f"run-{len(launched) + 1}"
        await runs.create(run_id=run_id, user_id=user_id, mode=mode, universe=universe,
                          params={"origin": origin})
        # started_at must fall on the simulated trading day
        await runs.collection.update_one({"run_id": run_id}, {"$set": {"started_at": MONDAY_10AM}})
        trading._RUNS[run_id] = asyncio.get_running_loop().create_task(_forever())
        launched.append((user_id, mode, origin))
        return run_id

    async def enable(user_id="alice"):
        await db["user_prefs"].insert_one({"user_id": user_id, "auto_paper_intraday": True})

    yield type("W", (), {"db": db, "redis": _Redis(), "launch": launch, "launched": launched, "enable": enable})
    for task in list(trading._RUNS.values()):
        task.cancel()
    trading._RUNS.clear()


def _tick(w, now):
    return autorun.tick(w.db, w.redis, now=now, launch=w.launch)


@pytest.mark.asyncio
async def test_starts_one_paper_intraday_run_in_session_then_only_renews(world):
    await world.enable()

    assert (await _tick(world, SUNDAY_10AM))["started"] == []
    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice"]
    assert (await _tick(world, MONDAY_10AM))["renewed"] == ["alice"]
    assert world.launched == [("alice", "INTRADAY", "auto")]
    assert world.redis.data["autorun:alice"] == "worker-a"


@pytest.mark.asyncio
async def test_users_who_did_not_opt_in_are_left_alone(world):
    await world.db["user_prefs"].insert_one({"user_id": "bob", "auto_paper_intraday": False})
    assert (await _tick(world, MONDAY_10AM))["started"] == []


@pytest.mark.asyncio
async def test_a_second_worker_never_starts_a_duplicate(world, monkeypatch):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    monkeypatch.setattr(autorun, "_TOKEN", "worker-b")
    monkeypatch.setattr(autorun, "_LOCAL", {})
    assert (await _tick(world, MONDAY_10AM))["started"] == []
    assert len(world.launched) == 1


@pytest.mark.asyncio
async def test_after_a_deploy_another_worker_takes_over(world, monkeypatch):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    # worker-a died: its task is gone, its row was swept as orphaned, and its
    # key expired.
    trading._RUNS.pop("run-1").cancel()
    await RunStore(world.db).close_orphaned()
    world.redis.data.clear()
    monkeypatch.setattr(autorun, "_TOKEN", "worker-b")
    monkeypatch.setattr(autorun, "_LOCAL", {})

    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice"]
    assert len(world.launched) == 2


@pytest.mark.asyncio
async def test_a_run_the_user_stopped_stays_stopped_today(world):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    trading._RUNS.pop("run-1").cancel()
    await RunStore(world.db).mark_stopped("run-1")

    assert (await _tick(world, MONDAY_10AM))["started"] == []
    assert len(world.launched) == 1


@pytest.mark.asyncio
async def test_a_crashing_run_is_retried_up_to_the_daily_cap(world):
    await world.enable()
    for attempt in range(autorun.MAX_STARTS_PER_DAY + 2):
        await _tick(world, MONDAY_10AM)
        run_id = f"run-{len(world.launched)}"
        if run_id in trading._RUNS:
            trading._RUNS.pop(run_id).cancel()
            await RunStore(world.db).mark_error(run_id, "boom")
    assert len(world.launched) == autorun.MAX_STARTS_PER_DAY


@pytest.mark.asyncio
async def test_a_manual_intraday_run_is_not_doubled(world):
    await world.enable()
    runs = RunStore(world.db)
    await runs.create(run_id="manual", user_id="alice", mode="INTRADAY", universe=[], params={"origin": "manual"})
    await runs.collection.update_one({"run_id": "manual"}, {"$set": {"started_at": MONDAY_10AM}})

    assert (await _tick(world, MONDAY_10AM))["started"] == []


@pytest.mark.asyncio
async def test_the_run_stops_at_the_close_and_when_turned_off(world, monkeypatch):
    stopped = []

    async def stop(run_id):
        stopped.append(run_id)
        return True
    monkeypatch.setattr(trading, "stop_background_run", stop)

    await world.enable()
    await _tick(world, MONDAY_10AM)
    assert (await _tick(world, MONDAY_EVENING))["stopped"] == ["alice"]
    assert stopped == ["run-1"]
    assert "autorun:alice" not in world.redis.data

    # Turned off mid-session: stopped on the next tick.
    await _tick(world, datetime(2026, 9, 29, 10, 0, tzinfo=IST))
    await world.db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"auto_paper_intraday": False}})
    assert (await _tick(world, datetime(2026, 9, 29, 10, 1, tzinfo=IST)))["stopped"] == ["alice"]


@pytest.mark.asyncio
async def test_a_long_term_run_starts_on_its_own_switch(world, monkeypatch):
    async def stop(run_id):
        return True
    monkeypatch.setattr(trading, "stop_background_run", stop)

    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})

    assert (await _tick(world, SUNDAY_10AM))["started"] == []
    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice:LONGTERM"]
    assert world.launched == [("alice", "LONGTERM", "auto")]
    assert world.redis.data["autorun:alice:LONGTERM"] == "worker-a"
    assert (await _tick(world, MONDAY_EVENING))["stopped"] == ["alice:LONGTERM"]


@pytest.mark.asyncio
async def test_both_switches_run_both_engines(world):
    await world.db["user_prefs"].insert_one(
        {"user_id": "alice", "auto_paper_intraday": True, "auto_paper_longterm": True}
    )
    assert sorted((await _tick(world, MONDAY_10AM))["started"]) == ["alice", "alice:LONGTERM"]
    assert sorted(m for _, m, _ in world.launched) == ["INTRADAY", "LONGTERM"]
