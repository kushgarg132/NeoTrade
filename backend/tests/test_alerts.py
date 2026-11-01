from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import alerts
from backend.configs.settings import settings

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    d = AsyncMongoMockClient()["t"]
    await d["users"].insert_many([{"id": "boss", "role": "admin"}, {"id": "bob"}])
    return d


@pytest.fixture
def sent(monkeypatch):
    class Out(list):
        pass

    out = Out()

    async def rec(db, user_id, text, html=False, buttons=None):
        out.append({"text": text, "html": html, "buttons": buttons})
        return rec.result

    rec.result = True
    monkeypatch.setattr("backend.guardrails.telegram.alert", rec)
    out.rec = rec
    return out


async def test_unknown_kind_raises(db):
    with pytest.raises(ValueError):
        await alerts.alert(db, "boss", "nope", "x")


async def test_instant_sends_card_and_logs_sent(db, sent):
    assert await alerts.alert(db, "boss", "exit", "Sell · TCS", ["Stop hit"]) is True
    assert sent[0]["text"] == "🔴 <b>Sell · TCS</b>\nStop hit" and sent[0]["html"] is True
    assert (await db["alerts"].find_one())["state"] == "sent"


def test_card_escapes_and_caps_three_lines():
    assert alerts.card("exit", "A<B", ["1", "2", "3", "4"]) == "🔴 <b>A&lt;B</b>\n1\n2\n3"


async def test_failed_send_logs_failed_and_returns_false(db, sent):
    sent.rec.result = False
    assert await alerts.alert(db, "boss", "exit", "x") is False
    assert (await db["alerts"].find_one())["state"] == "failed"


async def test_telegram_raising_is_swallowed(db, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr("backend.guardrails.telegram.alert", boom)
    assert await alerts.alert(db, "boss", "exit", "x") is False
    assert (await db["alerts"].find_one())["state"] == "failed"


async def test_log_write_failure_does_not_block_send(db, sent, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db")

    monkeypatch.setattr(type(db["alerts"]), "insert_one", boom)
    assert await alerts.alert(db, "boss", "exit", "x") is True
    assert len(sent) == 1


async def test_muted_kind_logs_muted_and_does_not_send(db, sent):
    await db["user_prefs"].insert_one({"user_id": "boss", "alert_mute": {"exit": True}})
    assert await alerts.alert(db, "boss", "exit", "x") is False
    assert not sent and (await db["alerts"].find_one())["state"] == "muted"


async def test_ideas_admin_only(db, sent):
    assert await alerts.alert(db, "bob", "ideas", "x") is False
    assert await db["alerts"].count_documents({}) == 0


async def test_batched_kind_queues(db, sent):
    assert await alerts.alert(db, "boss", "news", "x") is True
    assert (await db["alerts"].find_one())["state"] == "queued" and not sent


async def test_drain_groups_caps_and_claims(db):
    for i in range(7):
        await alerts.alert(db, "boss", "news", f"n{i}")
    await alerts.alert(db, "boss", "learning", "l")
    block, ids = await alerts.drain(db, "boss", NOW)
    assert block.startswith("<b>Since last update</b>") and "…and 2 more" in block and len(ids) == 8
    assert await db["alerts"].count_documents({"state": "queued"}) == 0
    assert (await alerts.drain(db, "boss", NOW)) == ("", [])


async def test_drain_skips_kind_muted_after_queueing(db):
    await alerts.alert(db, "boss", "news", "x")
    await db["user_prefs"].insert_one({"user_id": "boss", "alert_mute": {"news": True}})
    assert await alerts.drain(db, "boss", NOW) == ("", [])
    assert await db["alerts"].count_documents({"state": "queued"}) == 1


async def test_requeue_restores(db):
    await alerts.alert(db, "boss", "news", "x")
    _, ids = await alerts.drain(db, "boss", NOW)
    await alerts.requeue(db, ids)
    row = await db["alerts"].find_one()
    assert row["state"] == "queued" and row["digested_at"] is None


def test_sell_buttons_without_app_url_has_only_sell(monkeypatch):
    monkeypatch.setattr(settings, "APP_URL", None)
    rows = alerts.sell_buttons("TCS", 3, "/x")
    assert len(rows) == 1 and len(rows[0]) == 1 and rows[0][0]["text"] == "Sell ×3"
    monkeypatch.setattr(settings, "APP_URL", "https://a")
    assert alerts.sell_buttons("TCS", 3, "/x")[0][1] == {"text": "Open", "url": "https://a/x"}


def test_split():
    assert alerts.split("Title\nA\n\nB") == ("Title", ["A", "B"])


async def test_drain_with_microsecond_now(db):
    await alerts.alert(db, "boss", "news", "x")
    block, ids = await alerts.drain(db, "boss", datetime(2026, 11, 1, 9, 0, 0, 123456, tzinfo=timezone.utc))
    assert "• x" in block and len(ids) == 1
    assert await alerts.drain(db, "boss", NOW) == ("", [])
