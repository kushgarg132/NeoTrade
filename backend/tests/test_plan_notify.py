import json
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.plan import builder, notify
from backend.tests.test_datalayer_news import FakeRedis

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 6, 8, 46, tzinfo=IST)


def _doc(**kw):
    return {"trigger": "pre_open", "version": 1, "risk_multiplier": 0.85, "max_positions": 5, "skip_day": False,
            "add_symbols": ["IDEA"], "exits": [], "rationale": ["Neutral tape.", "Banks in focus."],
            "allow": [{"symbol": f"S{i}", "strategies": ["orb_breakout"]} for i in range(10)], **kw}


def test_pre_open_text():
    text = notify.plan_text(_doc())
    assert text.startswith("📋 Today's plan")
    assert "Neutral tape." in text and "Risk 0.85× · up to 5 positions" in text
    assert "S0, S1, S2, S3, S4, S5, S6, S7 +2 more" in text and "Added: IDEA" in text


def test_revision_text_lists_exits():
    text = notify.plan_text(_doc(trigger="regime_flip", version=2, exits=[{"symbol": "TCS", "reason": "guidance cut"}]))
    assert text.startswith("🔁 Plan updated (Regime change)") and "Exit TCS: guidance cut" in text


async def test_notify_without_telegram_is_a_quiet_false():
    assert await notify.notify_plan(AsyncMongoMockClient()["t"], "alice", _doc()) is False


async def test_builder_save_survives_a_failing_notify(monkeypatch):
    mongo, redis = AsyncMongoMockClient()["t"], FakeRedis()
    await mongo["user_prefs"].insert_one({"user_id": "alice", "universe": ["TCS"]})
    sent = []

    async def boom(db, user_id, doc):
        sent.append(doc["trigger"])
        raise RuntimeError("telegram down")
    monkeypatch.setattr(notify, "notify_plan", boom)

    async def complete(system, prompt):
        return json.dumps({"allow": [{"symbol": "TCS", "strategies": ["orb_breakout"]}], "rationale": ["x"]})
    doc = await builder.build_plan(mongo, redis, "alice", NOW, complete=complete)
    assert doc["trigger"] == "pre_open" and sent == ["pre_open"]
