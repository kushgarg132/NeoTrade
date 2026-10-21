"""Chat actions: a proposal changes nothing; only a confirm executes, once,
for its owner, before it expires, after every check is run again."""

import asyncio
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
from backend.risk import live_confirm
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
            "score": {"final": 0.6}, "strategy": "quality_momentum", "created_at": OPEN,
            # Against the real clock: store.decide refuses an expired proposal.
            "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
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


async def confirm_twice(db, user, action_id, credentials=None, redis=None):
    """Both taps of a real-money card: the second presents the first's token."""
    first = await confirm(db, redis, credentials, user, action_id)
    if first["status"] != "NEEDS_SECOND_TAP":
        return first
    return await confirm(db, redis, credentials, user, action_id, confirm_token=first["confirm_token"])


async def _propose(db, tool, args, user="alice"):
    out = await _tools(db, user)[tool].ainvoke(args)
    assert out.startswith("ACTION_CARD:"), out
    return json.loads(out[len("ACTION_CARD:"):])


async def test_proposing_changes_nothing(env):
    db = env["db"]
    await _propose(db, "propose_approve", {"suggestion_id": "s-alice", "live": True})
    await _propose(db, "propose_decline", {"suggestion_id": "s-alice"})
    await _propose(db, "propose_setting", {"name": "daily_loss_limit", "value": 5000})
    await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    assert (await db["suggestions"].find_one({"id": "s-alice"}))["status"] == "PENDING"
    assert (await PrefsStore(db).get("alice"))["daily_loss_limit"] == 1000.0
    assert env["broker"].placed == []
    assert await db["paper_orders"].count_documents({}) == 0


async def test_there_is_no_paper_approval(env):
    out = await _tools(env["db"])["propose_approve"].ainvoke({"suggestion_id": "s-alice"})
    assert not out.startswith("ACTION_CARD:") and "paper-trades proposals itself" in out


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
    card = await _propose(db, "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"})
    result = await confirm_twice(db, "alice", card["id"])
    assert result["status"] == "CONFIRMED"
    with pytest.raises(ActionRefused):
        await confirm_twice(db, "alice", card["id"])
    assert len(env["broker"].placed) == 1


async def test_there_are_no_paper_orders_on_the_users_account(env):
    out = await _tools(env["db"])["propose_order"].ainvoke(
        {"symbol": "INFY", "side": "BUY", "quantity": 1, "venue": "paper"})
    assert not out.startswith("ACTION_CARD:") and "no paper orders" in out


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
    second = await confirm(db, None, None, "alice", card["id"], confirm_token=first["confirm_token"])
    assert second["status"] == "CONFIRMED" and len(env["broker"].placed) == 1
    assert env["broker"].placed[0].strategy_name == "chat"


async def _live_card(env, user="alice"):
    return await _propose(env["db"], "propose_order", {"symbol": "INFY", "side": "BUY", "quantity": 10, "venue": "live"}, user)


async def test_live_order_without_a_token_never_places(env):
    """The old client-only second tap (second_tap=true) is gone: a confirm with
    no token only ever re-arms the card."""
    db = env["db"]
    card = await _live_card(env)
    for _ in range(3):
        assert (await confirm(db, None, None, "alice", card["id"]))["status"] == "NEEDS_SECOND_TAP"
    with pytest.raises(live_confirm.TokenRefused):
        await confirm(db, None, None, "alice", card["id"], confirm_token="made-up")
    assert env["broker"].placed == []
    assert (await ChatActionStore(db).get("alice", card["id"]))["status"] == "PROPOSED"


async def test_live_token_is_single_use(env):
    db = env["db"]
    first, second = await _live_card(env), await _live_card(env)
    token = (await confirm(db, None, None, "alice", first["id"]))["confirm_token"]
    taps = await asyncio.gather(*(confirm(db, None, None, "alice", first["id"], confirm_token=token) for _ in range(2)),
                                return_exceptions=True)
    assert sum(isinstance(t, dict) for t in taps) == 1 and len(env["broker"].placed) == 1
    await confirm(db, None, None, "alice", second["id"])
    with pytest.raises(live_confirm.TokenRefused, match="already used"):
        await confirm(db, None, None, "alice", second["id"], confirm_token=token)
    assert len(env["broker"].placed) == 1


async def test_live_token_refused_when_expired_mismatched_or_foreign(env, monkeypatch):
    db = env["db"]
    await PrefsStore(db).update("bob", {"per_trade_cap": 20000.0})
    mine, also_mine, bobs = await _live_card(env), await _live_card(env), await _live_card(env, "bob")
    token = (await confirm(db, None, None, "alice", mine["id"]))["confirm_token"]
    # Another user's card: 403, and the token survives for its owner.
    await confirm(db, None, None, "bob", bobs["id"])
    with pytest.raises(live_confirm.TokenRefused) as foreign:
        await confirm(db, None, None, "bob", bobs["id"], confirm_token=token)
    assert foreign.value.status == 403
    # Bound to its card: spent on the wrong one, then refused on its own.
    await confirm(db, None, None, "alice", also_mine["id"])
    with pytest.raises(live_confirm.TokenRefused, match="different order"):
        await confirm(db, None, None, "alice", also_mine["id"], confirm_token=token)
    with pytest.raises(live_confirm.TokenRefused, match="already used"):
        await confirm(db, None, None, "alice", mine["id"], confirm_token=token)
    # Expired after a minute.
    token = (await confirm(db, None, None, "alice", mine["id"]))["confirm_token"]
    later = live_confirm.time.monotonic() + live_confirm.TTL_SECONDS + 1
    monkeypatch.setattr(live_confirm.time, "monotonic", lambda: later)
    with pytest.raises(live_confirm.TokenRefused, match="expired"):
        await confirm(db, None, None, "alice", mine["id"], confirm_token=token)
    assert env["broker"].placed == []
    for card, user in ((mine, "alice"), (also_mine, "alice"), (bobs, "bob")):
        assert (await ChatActionStore(db).get(user, card["id"]))["status"] == "PROPOSED"


async def test_live_token_lives_in_redis_with_a_ttl(env):
    from backend.tests.test_datalayer_news import FakeRedis

    class Redis(FakeRedis):
        async def set(self, key, value, ex=None, **kw):
            self.ttl = ex
            return await super().set(key, value, ex=ex, **kw)

        async def delete(self, key):
            return 1 if self.data.pop(key, None) is not None else 0

    redis = Redis()
    card = await _live_card(env)
    token = (await confirm(env["db"], redis, None, "alice", card["id"]))["confirm_token"]
    assert list(redis.data) == [live_confirm.PREFIX + token] and redis.ttl == 60
    await confirm(env["db"], redis, None, "alice", card["id"], confirm_token=token)
    assert redis.data == {} and len(env["broker"].placed) == 1


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
        await confirm_twice(db, "alice", card["id"])
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
    params = {"symbol": "INFY", "side": "BUY", "quantity": 2, "product": "CNC", "venue": "live"}
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




async def test_mis_sell_is_not_capped_by_holdings(env):
    await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=5, product="MIS"), None)


async def test_cnc_live_sell_over_held_is_refused(env):
    await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=5, venue="live"), None)
    with pytest.raises(ActionRefused, match="You hold 5 INFY"):
        await actions._order_checks(env["db"], "alice", _order(side="SELL", quantity=6, venue="live"), None)


async def test_live_limit_reaches_broker_as_limit(env):
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    await confirm_twice(env["db"], "alice", card["id"])
    placed = env["broker"].placed[0]
    assert (placed.order_type, placed.limit_price) == ("LIMIT", 1490.0)


async def test_live_limit_resting_copy(env, monkeypatch):
    from backend.suggestions import service

    async def resting(broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status="ACKNOWLEDGED", filled_quantity=0, average_price=0.0)

    monkeypatch.setattr(env["broker"], "get_order_status", resting)
    monkeypatch.setattr(service, "LIVE_FILL_CHECKS", 1)
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    done = await confirm_twice(env["db"], "alice", card["id"])
    assert done["result"].startswith("Resting at your broker: limit ₹1,490.00, 0 of 2 filled.")






async def test_live_limit_refused_on_a_broker_without_limit_support(env, monkeypatch):
    class _MarketOnly:
        async def get_positions(self):
            return {}

    async def market_only(user_id, credentials):
        return _MarketOnly()

    monkeypatch.setattr(actions, "_active_broker", market_only)
    with pytest.raises(ActionRefused, match="does not take limit orders"):
        await actions._order_checks(env["db"], "alice", _order(venue="live", order_type="LIMIT", limit_price=1490.0), None)


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED"])
async def test_live_limit_rejected_is_not_reported_resting(env, monkeypatch, status):
    async def refused(broker_order_id):
        return BrokerOrderStatus(broker_order_id=broker_order_id, status=status, filled_quantity=0, average_price=0.0)

    monkeypatch.setattr(env["broker"], "get_order_status", refused)
    card = await _card(env["db"], _order(venue="live", order_type="LIMIT", limit_price=1490.0))
    done = await confirm_twice(env["db"], "alice", card["id"])
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
    done = await confirm_twice(env["db"], "alice", card["id"])
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


STRATEGY = {"setup": {"orb_break": {"range_minutes": 15}}, "filters": {}, "side": "long",
            "stop": {"setup_bar": True}, "target": {"r_multiple": 2.0}}


@pytest.fixture
def strategy_env(env, monkeypatch):
    """The confirm path calls the form's own handler, which reads the app-wide db and Redis."""
    from unittest.mock import AsyncMock

    from backend.builder import draft
    from backend.database import db as database
    from backend.tests.test_user_strategies_api import CountingRedis

    monkeypatch.setattr(database, "db", env["db"])
    monkeypatch.setattr(database, "redis", CountingRedis())
    spawn = AsyncMock()
    monkeypatch.setattr(draft, "spawn_test", spawn)
    return env["db"], spawn


async def test_strategy_card_creates_nothing_until_confirmed(strategy_env):
    db, spawn = strategy_env
    card = await _propose(db, "propose_strategy", {"name": "ORB 15", "thesis": "breakouts run", "spec": STRATEGY})
    assert card["kind"] == "strategy" and "first 15-minute range" in card["summary"]
    assert await db["built_strategies"].count_documents({}) == 0

    result = await confirm(db, None, None, "alice", card["id"])
    assert result["status"] == "CONFIRMED" and "ORB 15" in result["result"]
    doc = await db["built_strategies"].find_one({"owner_id": "alice"})
    assert doc["status"] == "testing" and doc["name"] == "ORB 15"
    spawn.assert_awaited_once_with(doc["slug"])


async def test_chat_swing_strategy_card(strategy_env):
    db, spawn = strategy_env
    swing = {"horizon": "swing", "setup": {"breakout_n": {"days": 20}}, "filters": {}, "side": "long",
             "stop": {"swing_low": True}, "target": {"r_multiple": 2.0}, "max_hold_days": {"days": 10}}
    card = await _propose(db, "propose_strategy", {"name": "Swing 20", "thesis": "", "spec": swing})
    assert card["kind"] == "strategy" and "10" in card["summary"]
    assert (await confirm(db, None, None, "alice", card["id"]))["status"] == "CONFIRMED"
    doc = await db["built_strategies"].find_one({"owner_id": "alice"})
    assert doc["spec"]["horizon"] == "swing" and doc["status"] == "testing"
    spec = actions._strategy_vocabulary()
    assert "SWING" in spec and "max_hold_days" in spec and "breakout_n" in spec


async def test_strategy_proposal_returns_the_refusal(strategy_env):
    db, _ = strategy_env
    no_stop = {k: v for k, v in STRATEGY.items() if k != "stop"}
    out = await _tools(db)["propose_strategy"].ainvoke({"name": "x", "thesis": "", "spec": no_stop})
    assert out.startswith("Refused:") and "stop" in out
    out = await _tools(db)["propose_strategy"].ainvoke({"name": " ", "thesis": "", "spec": STRATEGY})
    assert not out.startswith("ACTION_CARD:")


async def test_strategy_confirm_applies_the_form_limits(strategy_env):
    db, spawn = strategy_env
    await db["built_strategies"].insert_one({"slug": "busy", "owner_id": "alice", "status": "testing", "spec": {}})
    card = await _propose(db, "propose_strategy", {"name": "ORB 15", "thesis": "", "spec": STRATEGY})
    with pytest.raises(ActionRefused, match="still being tested"):
        await confirm(db, None, None, "alice", card["id"])
    spawn.assert_not_awaited()


async def test_other_user_cannot_confirm_a_strategy_card(strategy_env):
    db, spawn = strategy_env
    card = await _propose(db, "propose_strategy", {"name": "ORB 15", "thesis": "", "spec": STRATEGY})
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "bob", card["id"])
    assert await db["built_strategies"].count_documents({}) == 0


async def test_redeem_codes_for_each_refusal_kind():
    """Every refusal carries a stable machine-readable code; clients never match the text."""
    async def refusal(token, user="alice", subject="s", terms=1):
        with pytest.raises(live_confirm.TokenRefused) as caught:
            await live_confirm.redeem(None, user, subject, terms, token)
        return caught.value.code, caught.value.status

    assert await refusal(None) == ("confirm_missing", 409)
    assert await refusal("made-up") == ("confirm_expired", 409)
    token = await live_confirm.issue(None, "alice", "s", 1)
    assert await refusal(token, user="bob") == ("confirm_other_user", 403)
    assert await refusal(token, terms=2) == ("confirm_mismatch", 409)
    assert await refusal(token) == ("confirm_expired", 409)  # spent earlier: indistinguishable from expired

    class _Racing:  # the key was there at read time, a rival tap deleted it first
        async def get(self, key):
            return json.dumps(live_confirm._binding("alice", "s", 1))

        async def delete(self, key):
            return 0

    with pytest.raises(live_confirm.TokenRefused) as lost:
        await live_confirm.redeem(_Racing(), "alice", "s", 1, "t")
    assert lost.value.code == "confirm_spent"


async def test_confirm_route_carries_the_refusal_code(env, monkeypatch):
    """HTTP: `detail` stays text, `code` rides beside it (409, or 403 for another user's token)."""
    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.routers import chat_actions

    db = env["db"]
    await PrefsStore(db).update("bob", {"per_trade_cap": 20000.0})
    monkeypatch.setattr(chat_actions, "_db", lambda: db)
    who = {"id": "alice"}
    app = FastAPI()
    app.include_router(chat_actions.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id=who["id"], google_sub="g", email="a@x.com", name="A", created_at=datetime.now(timezone.utc))
    app.dependency_overrides[chat_actions.get_credential_store] = lambda: None
    client = TestClient(app)

    def tap(card, token=None):
        return client.post(f"/api/v1/chat/actions/{card['id']}/confirm", json={"confirm_token": token} if token else {})

    def refused(resp, status, code):
        assert resp.status_code == status and resp.json()["code"] == code and isinstance(resp.json()["detail"], str)

    card, other, bobs = await _live_card(env), await _live_card(env), await _live_card(env, "bob")
    token = tap(card).json()["confirm_token"]
    refused(tap(card, "made-up"), 409, "confirm_expired")
    who["id"] = "bob"
    tap(bobs)
    refused(tap(bobs, token), 403, "confirm_other_user")
    who["id"] = "alice"
    tap(other)
    refused(tap(other, token), 409, "confirm_mismatch")
    refused(tap(card, token), 409, "confirm_expired")  # spent on the wrong card above
    assert env["broker"].placed == []
