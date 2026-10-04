"""Chat actions: a proposal changes nothing; only a confirm executes, once,
for its owner, before it expires, after every check is run again."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.chat import actions
from backend.chat.actions import ActionRefused, ChatActionStore, action_tools, confirm
from backend.core.models import BrokerOrderStatus
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore

OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)  # Monday 10:30 IST
CLOSED = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)  # Sunday


class _Broker:
    def __init__(self):
        self.placed = []

    async def place_order(self, order):
        self.placed.append(order)
        return "B1"

    async def get_order_status(self, broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="FILLED", filled_quantity=10, average_price=1501.0)


@pytest.fixture
async def env(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="INFY", name="INFOSYS", instrument_token=1, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05,
    )])
    await PrefsStore(db).update("alice", {"per_trade_cap": 20000.0, "daily_loss_limit": 1000.0})
    for user in ("alice", "bob"):
        await db["suggestions"].insert_one({
            "id": f"s-{user}", "user_id": user, "symbol": "INFY", "side": "BUY", "mode": "LONGTERM",
            "status": "PENDING", "quantity": 2, "entry_ref": 1500.0, "stop": 1400.0, "target": 1700.0,
            "score": {"final": 0.6}, "created_at": OPEN, "expires_at": OPEN + timedelta(days=3),
        })
    broker = _Broker()
    clock = {"now": OPEN}

    async def mark(symbol):
        return 1500.0

    async def active_broker(user_id, credentials):
        return broker

    monkeypatch.setattr(actions, "_mark_price", mark)
    monkeypatch.setattr(actions, "_active_broker", active_broker)
    monkeypatch.setattr(actions, "_now", lambda: clock["now"])
    return {"db": db, "broker": broker, "clock": clock}


def _tools(db, user="alice", message="do it"):
    return {t.name: t for t in action_tools(db, None, user, message)}


async def _propose(db, tool, args, user="alice"):
    out = await _tools(db, user)[tool].ainvoke(args)
    assert out.startswith("ACTION_CARD:"), out
    return json.loads(out[len("ACTION_CARD:"):])


async def test_proposing_changes_nothing(env):
    db = env["db"]
    await _propose(db, "propose_approve", {"suggestion_id": "s-alice"})
    await _propose(db, "propose_decline", {"suggestion_id": "s-alice"})
    await _propose(db, "propose_setting", {"name": "daily_loss_limit", "value": 5000})
    await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    assert (await db["suggestions"].find_one({"id": "s-alice"}))["status"] == "PENDING"
    assert (await PrefsStore(db).get("alice"))["daily_loss_limit"] == 1000.0
    assert env["broker"].placed == []
    assert await db["paper_orders"].count_documents({}) == 0


async def test_propose_refuses_unknown_or_others_suggestion(env):
    db = env["db"]
    out = await _tools(db)["propose_approve"].ainvoke({"suggestion_id": "s-bob"})
    assert not out.startswith("ACTION_CARD:")
    assert await db["chat_actions"].count_documents({}) == 0


@pytest.mark.parametrize("args", [
    {"symbol": "INFY", "side": "BUY", "quantity": 0},
    {"symbol": "NOPE", "side": "BUY", "quantity": 1},
    {"symbol": "INFY", "side": "BUY", "quantity": 20},  # 20 x 1500 > 20,000 cap
])
async def test_propose_order_refuses_bad_input(env, args):
    db = env["db"]
    out = await _tools(db)["propose_order"].ainvoke(args)
    assert not out.startswith("ACTION_CARD:")
    assert await db["chat_actions"].count_documents({}) == 0


async def test_confirm_runs_once(env):
    db = env["db"]
    card = await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "paper"})
    result = await confirm(db, None, None, "alice", card["id"])
    assert result["status"] == "CONFIRMED"
    trades = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)
    assert len(trades) == 1 and trades[0]["strategy"] == "chat"
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "alice", card["id"])
    assert await db["paper_trades"].count_documents({"user_id": "alice"}) == 1


async def test_confirm_refuses_expired_and_other_users(env):
    db = env["db"]
    card = await _propose(db, "propose_setting", {"name": "daily_loss_limit", "value": 5000})
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "bob", card["id"])
    env["clock"]["now"] = OPEN + timedelta(minutes=6)
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "alice", card["id"])
    assert (await ChatActionStore(db).get("alice", card["id"]))["status"] == "EXPIRED"
    assert (await PrefsStore(db).get("alice"))["daily_loss_limit"] == 1000.0


async def test_live_order_needs_second_tap(env):
    db = env["db"]
    card = await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    assert card["needs_second_tap"] is True
    first = await confirm(db, None, None, "alice", card["id"])
    assert first["status"] == "NEEDS_SECOND_TAP" and env["broker"].placed == []
    assert (await ChatActionStore(db).get("alice", card["id"]))["status"] == "PROPOSED"
    second = await confirm(db, None, None, "alice", card["id"], second_tap=True)
    assert second["status"] == "CONFIRMED" and len(env["broker"].placed) == 1
    assert env["broker"].placed[0].strategy_name == "chat"


@pytest.mark.parametrize("breaks", ["kill_switch", "market_closed", "no_broker"])
async def test_live_order_rechecks_at_confirm(env, monkeypatch, breaks):
    db = env["db"]
    card = await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    if breaks == "kill_switch":
        await KillSwitchStore(db).trip("alice", date(2026, 10, 5), "loss", -2000.0)
    elif breaks == "market_closed":
        env["clock"]["now"] = OPEN.replace(hour=11)  # 16:30 IST
    else:
        async def none(user_id, credentials):
            return None
        monkeypatch.setattr(actions, "_active_broker", none)
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "alice", card["id"], second_tap=True)
    assert env["broker"].placed == []


async def test_setting_change_is_whitelisted(env):
    db = env["db"]
    out = await _tools(db)["propose_setting"].ainvoke({"name": "account_size", "value": 1})
    assert not out.startswith("ACTION_CARD:")
    card = await _propose(db, "propose_setting", {"name": "daily_loss_limit", "value": 5000})
    await confirm(db, None, None, "alice", card["id"])
    assert (await PrefsStore(db).get("alice"))["daily_loss_limit"] == 5000.0


async def test_confirm_route_maps_refusal_to_409(env, monkeypatch):
    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.routers import chat_actions

    monkeypatch.setattr(chat_actions, "_db", lambda: env["db"])
    app = FastAPI()
    app.include_router(chat_actions.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(id="alice", google_sub="g", email="a@x.com", name="A", created_at=datetime.now(timezone.utc))
    app.dependency_overrides[chat_actions.get_credential_store] = lambda: None
    resp = TestClient(app).post("/api/v1/chat/actions/missing/confirm", json={})
    assert resp.status_code == 409


async def test_memory_card_saves_only_on_confirm(env):
    from backend.profile.store import ProfileStore

    db = env["db"]
    card = await _propose(db, "propose_memory", {"facts": ["Saving for a house"]})
    assert card["kind"] == "memory" and card["summary"] == "Remember: Saving for a house"
    assert (await ProfileStore(db).get("alice"))["memories"] == []
    for bad in (["   "], ["x" * 201], []):
        out = await _tools(db)["propose_memory"].ainvoke({"facts": bad})
        assert not out.startswith("ACTION_CARD:")
    result = await confirm(db, None, None, "alice", card["id"])
    assert result["status"] == "CONFIRMED"
    memories = (await ProfileStore(db).get("alice"))["memories"]
    assert [(m["text"], m["source"]) for m in memories] == [("Saving for a house", "chat")]
    again = await _tools(db)["propose_memory"].ainvoke({"facts": ["saving for a house"]})
    assert "already" in again


async def test_several_facts_are_one_card_and_all_saved(env):
    from backend.profile.store import ProfileStore

    db = env["db"]
    await ProfileStore(db).add_memory("alice", "Monthly SIP budget is ₹15,000", "chat")
    card = await _propose(db, "propose_memory", {"facts": [
        "Monthly SIP budget is ₹15,000", "No debt or gold investments", "No big expenses planned", "No debt or gold investments",
    ]})
    # Already-saved and repeated facts are dropped from the one card.
    assert card["summary"] == "Remember:\n• No debt or gold investments\n• No big expenses planned"
    result = await confirm(db, None, None, "alice", card["id"])
    assert result["result"] == "Saved 2 things to your profile memory."
    assert len((await ProfileStore(db).get("alice"))["memories"]) == 3
