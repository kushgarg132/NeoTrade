"""The admin Lab switch (app_settings.lab_on, default off) is an outer gate
on the experimental AI jobs: each one skips cleanly while it is off."""

import logging
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import app_settings
from backend.engine.session import IST
from backend.tests.test_autorun import MONDAY_10AM, _tick, world  # noqa: F401 (fixture)

FRIDAY = datetime(2026, 10, 9, 16, 0, tzinfo=IST)


@pytest.fixture
def lab_off(monkeypatch):
    skipped = []

    async def off(job, db=None):
        skipped.append(job)
        return False

    monkeypatch.setattr(app_settings, "lab_on", off)
    return skipped


@pytest.mark.real_lab
async def test_lab_defaults_off_logs_once_and_turns_on(monkeypatch, caplog):
    db = AsyncMongoMockClient()["lab"]
    monkeypatch.setattr(app_settings, "_cache_loaded_at", 0.0)
    monkeypatch.setattr(app_settings, "_lab_logged", set())
    with caplog.at_level(logging.INFO, logger="backend.app_settings"):
        assert await app_settings.lab_on("the monthly re-tune", db) is False
        assert await app_settings.lab_on("the monthly re-tune", db) is False
    assert [r.message for r in caplog.records] == ["Lab is off: skipping the monthly re-tune."]
    await app_settings.AppSettingsStore(db).set_lab_enabled(True)
    assert await app_settings.lab_on("the monthly re-tune", db) is True
    assert await app_settings.AppSettingsStore(db).get_lab_enabled() is True


async def test_lab_off_stops_the_intraday_auto_run(world, lab_off):  # noqa: F811
    await world.enable()
    assert (await _tick(world, MONDAY_10AM))["started"] == []
    assert "the intraday auto-run" in lab_off


async def test_lab_off_builds_no_game_plan(lab_off, monkeypatch):
    from backend.engine import autorun
    from backend.plan import builder

    build = AsyncMock()
    monkeypatch.setattr(builder, "build_plan", build)
    assert await autorun._preopen_plans(AsyncMongoMockClient()["t"], None, MONDAY_10AM, ["alice"]) == []
    build.assert_not_called()


async def test_lab_off_revises_no_plan(lab_off):
    from backend.plan import revise

    assert await revise.loop(AsyncMongoMockClient()["t"], None, now=MONDAY_10AM) == 0
    assert lab_off == ["AI game plan revisions"]


async def test_lab_off_keeps_news_away_from_the_autopilot(lab_off, monkeypatch):
    from backend.datalayer import reactor
    from backend.engine import autorun
    from backend.suggestions import notify as notify_module, scan as scan_module, thesis

    async def scan_universe(db, **kw):
        return [{"id": "s1", "symbol": "TCS"}]

    handed = AsyncMock()
    monkeypatch.setattr(scan_module, "scan_universe", scan_universe)
    monkeypatch.setattr(thesis, "attach_theses", AsyncMock())
    monkeypatch.setattr(autorun, "_autopilot_proposals", handed)
    monkeypatch.setattr(notify_module, "notify", AsyncMock())
    prefs = {"user_id": "u1", "account_size": 1.0, "max_exposure": 1.0, "autopilot_enabled": True,
             "autopilot_news": True}
    await reactor._scan_user(AsyncMongoMockClient()["t"], None, prefs, ["TCS"], MONDAY_10AM,
                             ai_symbols=frozenset({"TCS"}))
    handed.assert_not_called()


async def test_lab_off_skips_the_builder_retune_and_learning(lab_off, monkeypatch):
    from backend import scheduler
    from backend.builder import draft
    from backend.learning import adapt, retune

    db = AsyncMongoMockClient()["t"]
    spawn, learn = AsyncMock(), AsyncMock(return_value=["x"])
    monkeypatch.setattr(draft, "spawn", spawn)
    monkeypatch.setattr(retune, "spawn", spawn)
    monkeypatch.setattr(adapt, "learn", learn)
    await db["paper_trades"].insert_one({"user_id": "alice"})
    assert await draft.start_if_due(db, FRIDAY) is False
    assert await retune.start_if_due(db, FRIDAY) is False
    assert await scheduler._learn(db, FRIDAY) == 0
    spawn.assert_not_called()
    learn.assert_not_called()
    assert await db["retune_runs"].count_documents({}) == 0
    assert lab_off == ["the weekly strategy builder", "the monthly re-tune", "nightly learning"]
