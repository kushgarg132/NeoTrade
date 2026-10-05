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
from backend.core.models import BrokerOrderStatus, Holding
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore

OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)  # Monday 10:30 IST
CLOSED = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)  # Sunday


class _Broker:
    SUPPORTS_LIMIT = True

    def __init__(self):
        self.placed = []

    async def place_order(self, order):
        self.placed.append(order)
        return "B1"

    async def get_order_status(self, broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="FILLED", filled_quantity=10, average_price=1501.0)

    async def get_positions(self):
        return {}

    async def get_holdings(self):
        return [Holding(symbol="INFY", quantity=5, avg_price=1400.0, broker="upstox")]


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


# ---------------------------------------------------------------------------
# Order ticket: LIMIT, the ±20% band and the delivery-oversell guard.
# ---------------------------------------------------------------------------

def _order(**over):
    params = {"symbol": "INFY", "side": "BUY", "quantity": 2, "product": "CNC", "venue": "paper"}
    params.update(over)
    return params


async def _card(db, params):
    return await ChatActionStore(db).propose(
        "alice", "order", params, "ticket", params["venue"], params["venue"] == "live", "order ticket",
    )


@pytest.mark.parametrize("limit", [1801.0, 1199.0])
async def test_limit_outside_band_is_refused(env, limit):
    with pytest.raises(ActionRefused, match="more than 20% from the price"):
        await actions._order_checks(env["db"], "alice", _order(order_type="LIMIT", limit_price=limit), None)


async def test_cap_uses_limit_price(env):
    await actions._order_checks(env["db"], "alice", _order(order_type="LIMIT", limit_price=1250.0, quantity=16), None)
    with pytest.raises(ActionRefused, match="per-trade cap"):
        await actions._order_checks(env["db"], "alice", _order(quantity=16), None)


async def test_cnc_paper_sell_over_held_is_refused(env):
    from backend.engine.persistence import LedgerStore
    from backend.suggestions.service import execute_suggestion

    await execute_suggestion({"symbol": "INFY", "side": "BUY", "quantity": 3, "mode": "LONGTERM"},
                             LedgerStore(env["db"], user_id="alice"), 1500.0)
    await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=3), None)
    with pytest.raises(ActionRefused, match="You hold 3 INFY; a delivery sell can't be more than that."):
        await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=4), None)


async def test_mis_sell_is_not_capped_by_holdings(env):
    await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=5, product="MIS"), None)


async def test_cnc_live_sell_over_held_is_refused(env):
    await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=5, venue="live"), None)
    with pytest.raises(ActionRefused, match="You hold 5 INFY"):
        await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=6, venue="live"), None)


async def test_live_limit_reaches_broker_as_limit(env):
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    await confirm(env["db"], None, None, "alice", card["id"], second_tap=True)
    placed = env["broker"].placed[0]
    assert (placed.order_type, placed.limit_price) == ("LIMIT", 1490.0)


async def test_live_limit_resting_copy(env, monkeypatch):
    from backend.suggestions import service

    async def resting(broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="ACKNOWLEDGED", filled_quantity=0, average_price=0.0)

    monkeypatch.setattr(env["broker"], "get_order_status", resting)
    monkeypatch.setattr(service, "LIVE_FILL_CHECKS", 1)
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    done = await confirm(env["db"], None, None, "alice", card["id"], second_tap=True)
    assert done["result"].startswith("Resting at your broker: limit ₹1,490.00, 0 of 2 filled.")


async def test_market_chat_card_unchanged(env):
    card = await _card(env["db"], _order())
    done = await confirm(env["db"], None, None, "alice", card["id"])
    assert done["result"] == "Paper BUY 2 INFY filled at ₹1,500.00."


async def test_paper_limit_card_rests_then_fills(env):
    from backend.engine import paper_orders

    card = await _card(env["db"], _order(order_type="LIMIT", limit_price=1490.0))
    done = await confirm(env["db"], None, None, "alice", card["id"])
    assert done["result"] == "Paper limit ₹1,490.00 is open until 15:30; it fills if the price gets there."

    async def mark(symbol):
        return 1489.0

    assert await paper_orders.sweep(env["db"], mark, OPEN) == 1
    assert (await env["db"]["paper_orders"].find_one({"user_id": "alice"}))["status"] == "FILLED"


async def test_live_limit_refused_on_a_broker_without_limit_support(env, monkeypatch):
    class _MarketOnly:
        async def get_positions(self):
            return {}

    async def market_only(user_id, credentials):
        return _MarketOnly()

    monkeypatch.setattr(actions, "_active_broker", market_only)
    with pytest.raises(ActionRefused, match="Limit orders on your account need Upstox"):
        await actions._order_checks(env["db"], "alice", _order(venue="live", order_type="LIMIT", limit_price=1490.0), None)


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED"])
async def test_live_limit_rejected_is_not_reported_resting(env, monkeypatch, status):
    async def refused(broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status=status, filled_quantity=0, average_price=0.0)

    monkeypatch.setattr(env["broker"], "get_order_status", refused)
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    done = await confirm(env["db"], None, None, "alice", card["id"], second_tap=True)
    assert done["result"].startswith(f"Your broker {status.lower()} the limit order")
    assert "Resting" not in done["result"]


async def test_equity_approve_card_live_reaches_mine(env, monkeypatch):
    from backend.routers import suggestions as routes

    async def mine(user_id):
        return env["broker"]

    monkeypatch.setattr(routes, "_mine_broker", mine)
    monkeypatch.setattr(routes, "_now", lambda: OPEN)
    monkeypatch.setattr(routes, "db", type("_Db", (), {"db": env["db"], "redis": None})())
    card = await _propose(env["db"], "propose_approve", {"suggestion_id": "s-alice", "live": True})
    assert card["needs_second_tap"] is True
    done = await confirm(env["db"], None, None, "alice", card["id"], second_tap=True)
    assert done["status"] == "CONFIRMED"
    assert env["broker"].placed[0].symbol == "INFY"


async def test_pending_cards_are_the_callers_unexpired_proposals(env, monkeypatch):
    from backend.auth.dependency import get_current_user
    from backend.routers import chat_actions

    store = ChatActionStore(env["db"])
    fresh = await store.propose("alice", "order", {}, "fresh", "paper", False, "m")
    stale = await store.propose("alice", "order", {}, "stale", "paper", False, "m")
    done = await store.propose("alice", "order", {}, "done", "paper", False, "m")
    await store.propose("bob", "order", {}, "bob's", "paper", False, "m")
    await env["db"]["chat_actions"].update_one({"id": stale["id"]}, {"$set": {"expires_at": OPEN - timedelta(minutes=1)}})
    await store.set_status(done["id"], "CONFIRMED")

    monkeypatch.setattr(chat_actions, "_db", lambda: env["db"])
    app = FastAPI()
    app.include_router(chat_actions.router)
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"id": "alice"})()
    body = TestClient(app).get("/chat/actions/pending").json()
    assert [c["id"] for c in body] == [fresh["id"]]
    assert set(body[0]) == {"id", "kind", "summary", "venue", "needs_second_tap", "expires_at"}


# ---------------------------------------------------------------------------
# Order modify on the user's own account: same limits as a new order.
# ---------------------------------------------------------------------------

class _OrdersBroker:
    def __init__(self):
        self.modified = []

    async def get_orders(self):
        return [{"order_id": "B9", "symbol": "INFY", "side": "BUY", "quantity": 1, "price": 1500.0, "status": "open"}]

    async def modify_order(self, order_id, quantity=None, price=None, trigger_price=None):
        self.modified.append((order_id, quantity, price))


@pytest.mark.parametrize("params,why", [
    ({"order_id": "B9", "quantity": 5000, "price": None}, "per-trade cap"),
    ({"order_id": "B9", "quantity": None, "price": -1.0}, "price above 0"),
    ({"order_id": "B9", "quantity": 0, "price": None}, "whole number above zero"),
])
async def test_modify_is_held_to_the_same_limits_as_a_new_order(env, params, why):
    with pytest.raises(ActionRefused, match=why):
        await actions._modify_checks(env["db"], "alice", _OrdersBroker(), params)


async def test_modify_cannot_add_shares_after_the_kill_switch_trips(env):
    from backend.engine.session import IST
    await KillSwitchStore(env["db"]).trip("alice", OPEN.astimezone(IST).date(), reason="test", equity=-1.0)
    with pytest.raises(ActionRefused, match="daily loss limit was hit"):
        await actions._modify_checks(env["db"], "alice", _OrdersBroker(), {"order_id": "B9", "quantity": 2, "price": None})
    # lowering the price of the same quantity is still fine
    await actions._modify_checks(env["db"], "alice", _OrdersBroker(), {"order_id": "B9", "quantity": None, "price": 1490.0})


async def test_modify_within_limits_passes(env):
    await actions._modify_checks(env["db"], "alice", _OrdersBroker(), {"order_id": "B9", "quantity": 10, "price": 1490.0})
