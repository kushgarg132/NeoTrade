"""Load-time fixes (2026-10-24): the pulse a request reads is shared for 30 s per user,
and every response says how long the server took (Server-Timing; slow ones are logged)."""

import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.portfolio import digest
from backend.timing import add_timing


async def test_cached_pulse_reuses_one_read_per_user(monkeypatch):
    calls = []

    async def fake_pulse(db, user_id, now=None):
        calls.append(user_id)
        await asyncio.sleep(0)
        return {"user": user_id}

    monkeypatch.setattr(digest, "pulse", fake_pulse)
    digest._PULSE_CACHE.clear()
    db = object()
    a, b = await asyncio.gather(digest.cached_pulse(db, "u1"), digest.cached_pulse(db, "u1"))
    assert a == b == {"user": "u1"} and calls == ["u1"]
    await digest.cached_pulse(db, "u2")
    assert calls == ["u1", "u2"]
    monkeypatch.setattr(digest, "PULSE_TTL_S", 0)
    await digest.cached_pulse(db, "u1")
    assert calls == ["u1", "u2", "u1"]


def test_server_timing_header_and_slow_log(caplog, monkeypatch):
    app = FastAPI()
    add_timing(app)

    @app.get("/x")
    async def x():
        return {}

    monkeypatch.setattr("backend.timing.SLOW_MS", -1)
    with caplog.at_level(logging.WARNING, logger="backend.timing"):
        r = TestClient(app).get("/x")
    assert r.headers["server-timing"].startswith("app;dur=")
    assert any("slow request GET /x" in m for m in caplog.messages)
