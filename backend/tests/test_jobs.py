"""backend/jobs.py: the jobs entry point and the API's RUN_BACKGROUND_JOBS flag."""

import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import jobs, server

EXPECTED = {"scheduler", "order_sweeps", "guardrail_monitor", "telegram_bot", "autorun", "data_quality_watch"}


@pytest.fixture
def started(monkeypatch):
    """Replaces every loop's start() with a recorder."""
    from backend import scheduler
    from backend.engine import autorun, sweeps
    from backend.guardrails import monitor, telegram_bot
    from backend.system import data_quality

    names = []
    for name, mod in [("scheduler", scheduler), ("order_sweeps", sweeps), ("guardrail_monitor", monitor),
                      ("telegram_bot", telegram_bot), ("autorun", autorun),
                      ("data_quality_watch", data_quality)]:
        monkeypatch.setattr(mod, "start", lambda *a, _n=name, **k: names.append(_n))
    return names


def test_start_loops_starts_the_expected_set(started):
    assert set(jobs.start_loops(object(), None)) == EXPECTED
    assert set(started) == EXPECTED


@pytest.fixture
def api_startup(monkeypatch):
    """Runs server.startup_db_client on an in-memory Mongo with no Redis or network."""
    async def noop(*a, **k):
        return None

    mongo = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(server.db, "connect_to_database", noop)
    monkeypatch.setattr(server.db, "db", mongo, raising=False)
    monkeypatch.setattr(server.db, "redis", None, raising=False)
    monkeypatch.setattr(server, "require_jwt_secret", lambda: None)
    monkeypatch.setattr(server, "refresh_from_free_public_sources", noop)
    monkeypatch.setattr(server, "refresh_instruments", noop)
    monkeypatch.setattr(server.ws_pump, "start", lambda *a, **k: None)
    monkeypatch.setattr(server.broadcast, "listen_forever", noop)
    return server.startup_db_client


async def test_api_starts_loops_when_flag_absent_or_on(api_startup, started):
    # The default is today's behaviour: no env flag, loops in the API.
    assert server.settings.RUN_BACKGROUND_JOBS is True
    await api_startup()
    assert set(started) == EXPECTED


async def test_api_starts_none_when_flag_off(api_startup, started, monkeypatch):
    monkeypatch.setattr(server.settings, "RUN_BACKGROUND_JOBS", False)
    await api_startup()
    assert started == []


async def test_heartbeat_age():
    class R:
        def __init__(self, value):
            self.value = value

        async def get(self, key):
            assert key == jobs.HEARTBEAT_KEY
            return self.value

    assert await jobs.heartbeat_age(R(None)) is None
    assert await jobs.heartbeat_age(None) is None
    import time

    assert 0 <= await jobs.heartbeat_age(R(str(int(time.time()) - 5))) - 5 <= 1
