"""The daily answer (portfolio/digest.py): the user's own account priced
from quotes, movers with the news behind them, verdict changes, and the two
Telegram messages."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.session import IST
from backend.portfolio import digest, service

NOW = datetime(2026, 10, 15, 10, 30, tzinfo=IST)


def _h(symbol, broker, qty=10, avg=100.0, last=100.0, close=100.0):
    return {"symbol": symbol, "isin": symbol, "quantity": qty, "avg_price": avg, "last_price": last,
            "close_price": close, "broker": broker, "kind": "STOCK"}


@pytest.fixture
async def db(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    await db["users"].insert_one({"id": "alice", "role": "admin"})
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"upstox": "mine", "kite": "ai"}})
    await db["portfolio_snapshots"].insert_one({
        "user_id": "alice", "at": NOW - timedelta(days=1),
        "raw_holdings": [_h("UP", "upstox"), _h("DOWN", "upstox"), _h("FLAT", "upstox"), _h("AIONLY", "kite")],
        "holdings": [{"symbol": "DOWN", "verdict": "SELL", "previous_verdict": "HOLD", "reason_codes": ["deep_loss"]},
                     {"symbol": "UP", "verdict": "HOLD", "previous_verdict": "HOLD"}],
    })
    await db["news_items"].insert_one({
        "title": "DOWN <misses> & cuts guidance", "url": "https://x", "published_at": NOW - timedelta(hours=2),
        "impacts": [{"target": "DOWN", "direction": -0.8, "impact": 8.0}]})
    monkeypatch.setattr(service, "mark_prices", AsyncMock(return_value={"UP": 105.0, "DOWN": 90.0, "FLAT": 100.0, "AIONLY": 200.0}))
    monkeypatch.setattr(service.bars, "prev_closes", AsyncMock(return_value={"UP": 100.0, "DOWN": 100.0, "FLAT": 100.0}))
    return db


async def test_pulse_is_the_users_own_account_with_movers_and_why(db):
    p = await digest.pulse(db, "alice", NOW)
    assert p["value"] == 1050 + 900 + 1000  # the AI account's holding is not in it
    assert p["day_change"] == 50 - 100
    assert [m["symbol"] for m in p["movers"]][:2] == ["DOWN", "UP"]
    assert p["movers"][0]["why"]["title"].startswith("DOWN <misses>")
    assert p["verdict_changes"] == [{"symbol": "DOWN", "from": "HOLD", "to": "SELL", "reasons": ["deep_loss"]}]


async def test_verdict_changes_stay_hidden_from_non_admins_without_the_switch(db):
    await db["users"].update_one({"id": "alice"}, {"$set": {"role": "user"}})
    assert (await digest.pulse(db, "alice", NOW))["verdict_changes"] == []


async def test_messages_escape_headlines_for_telegram_html(db):
    p = await digest.pulse(db, "alice", NOW)
    text = digest.postclose_text(p, {"mine": -120.0, "ai": 35.0}, [{"title": "RBI policy"}])
    assert "&lt;misses&gt; &amp; cuts" in text and "<misses>" not in text
    assert "DOWN: HOLD → SELL" in text and "you −₹120 · AI +₹35" in text and "Tomorrow: RBI policy" in text
    pre = digest.premarket_text(p, {"DOWN": p["movers"][0]["why"]}, 0, {"enabled": True, "live": False, "deployed": 0})
    assert "no strategy has earned it yet" in pre and "autopilot paper" in pre


class _Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, nx=False, px=None):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


async def test_premarket_goes_once_in_its_window(db, monkeypatch):
    from backend.suggestions import notify

    sent = []

    async def capture(db_, user_id, text):
        sent.append(text)
        return True

    monkeypatch.setattr(notify, "notify", capture)
    redis = _Redis()
    morning = NOW.replace(hour=8, minute=40)
    assert await digest.send_premarket(db, redis, morning) == 0          # 08:40: too early
    assert await digest.send_premarket(db, redis, morning.replace(minute=46)) == 1
    assert await digest.send_premarket(db, redis, morning.replace(minute=55)) == 0  # once a day
    assert "Before the open" in sent[0] and "DOWN" in sent[0]


async def test_postclose_skips_a_morning_catch_up(db):
    assert await digest.send_postclose(db, NOW.replace(hour=9, minute=20)) == 0
