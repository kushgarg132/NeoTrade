"""The fenced autopilot on the AI account: every order passes the fence or is
refused (logged, never retried), paper first, a one-tap stop on Telegram,
and it never touches the user's own account."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import fence, service
from backend.autopilot.fence import FenceState, round_trip_cost
from backend.autopilot.service import AutopilotOrder
from backend.core.models import Side
from backend.engine.session import IST

OPEN = datetime(2026, 10, 6, 11, 0, tzinfo=IST)
# The shared trading limits (paper and live, Practice and the autopilot).
PREFS = {"autopilot_enabled": True, "autopilot_live": False, "account_size": 25_000.0, "max_exposure": 25_000.0,
         "per_trade_cap": 5_000.0, "max_trades_per_day": 5, "daily_loss_limit": 1_000.0}


def _state(**kw):
    base = dict(deployed=0.0, entries_today=0, held={}, kill_tripped=False, session_ok=True)
    return FenceState(**{**base, **kw})


def _order(symbol="INFY", side=Side.BUY, qty=1, product="CNC", source="chat"):
    return AutopilotOrder(symbol=symbol, side=side, quantity=qty, product=product, source=source, reason="test")


@pytest.mark.parametrize("order,price,state,refusal", [
    (_order(qty=5), 1000.0, _state(), None),                                  # exactly the per-trade cap
    (_order(qty=5), 1000.2, _state(), "per-trade cap"),
    (_order(qty=1), 1000.0, _state(deployed=24_000.0), None),                 # exactly fills capital
    (_order(qty=1), 1001.0, _state(deployed=24_000.0), "max invested"),
    (_order(), 100.0, _state(entries_today=5), "trades today"),
    (_order(symbol="NOTANIFTY"), 100.0, _state(), "universe"),
    (_order(product="NRML"), 100.0, _state(), "NSE equity"),
    (_order(), 100.0, _state(kill_tripped=True), "loss limit"),
    (_order(), 100.0, _state(session_ok=False), "market"),
    (_order(), 100.0, _state(held={"INFY": (5, "CNC")}), "already holding"),
    (_order(side=Side.SELL, qty=50), 1000.0, _state(held={"INFY": (50, "CNC")}, deployed=25_000.0, entries_today=5), None),
    # C1: no overselling, no shorts by product mismatch, no negative quantities.
    (_order(side=Side.SELL, qty=1000, product="MIS"), 1000.0, _state(held={"INFY": (5, "CNC")}), "holds"),
    (_order(side=Side.SELL, qty=6), 1000.0, _state(held={"INFY": (5, "CNC")}), "holds"),
    (_order(qty=-10), 100.0, _state(), "quantity"),
])
def test_fence_limits(order, price, state, refusal):
    result = fence.check(order, price, state, PREFS)
    if refusal is None:
        assert result is None
    else:
        assert result and refusal in result


def test_zero_trades_per_day_means_no_daily_count():
    """0 is 'off' for trades per day, as on Settings > Safety, which shares the field."""
    prefs = {**PREFS, "max_trades_per_day": 0}
    assert fence.check(_order(), 100.0, _state(entries_today=50), prefs) is None


def test_fence_off_refuses_entries_but_never_blocks_an_exit():
    off = {**PREFS, "autopilot_enabled": False}
    assert "off" in fence.check(_order(), 100.0, _state(), off)
    held = _state(held={"INFY": (3, "CNC")})
    assert fence.check(_order(side=Side.SELL, qty=3), 100.0, held, off) is None


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    sent = []

    async def notify(db_, user_id, text, stop_button=True):
        sent.append(text)
        return True

    async def marks(db_, symbols, **_):
        return {s: 1000.0 for s in symbols}

    monkeypatch.setattr(service, "_notify", notify)
    monkeypatch.setattr(service, "mark_prices", marks)
    return db, sent


async def _prefs(db, **kw):
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"},
                                       **PREFS, **kw})


async def test_submit_paper_fills_logs_and_notifies(world):
    db, sent = world
    await _prefs(db)
    result = await service.submit(db, None, "alice", _order(qty=2), now=OPEN)
    assert result["status"] == "FILLED"
    trades = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)  # the Practice book
    assert len(trades) == 1 and trades[0]["strategy"] == "autopilot:chat"
    assert await db["autopilot_log"].count_documents({"user_id": "alice", "status": "FILLED"}) == 1
    assert sent and sent[0].startswith("🤖 AI bought 2 INFY")


async def test_submit_refusal_is_logged_not_retried(world):
    db, sent = world
    await _prefs(db)
    result = await service.submit(db, None, "alice", _order(qty=6), now=OPEN)  # ₹6,000 > ₹5,000 cap
    assert result["status"] == "REFUSED" and "per-trade cap" in result["reason"]
    assert await db["paper_trades"].count_documents({}) == 0
    assert await db["autopilot_log"].count_documents({"status": "REFUSED"}) == 1 and len(sent) == 1


async def test_ai_session_missing_in_live_mode_refuses_without_fallback(world, monkeypatch):
    from backend.brokers import roles

    db, _ = world
    await _prefs(db, autopilot_live=True)

    async def no_ai(user_id, role, credentials, redis=None, roles=None, get_adapter=None):
        assert role == "ai"
        raise roles_module.RoleUnavailable("ai", "The AI account (Kite) is not logged in today.")

    roles_module = roles
    monkeypatch.setattr(service, "adapter_for", no_ai)
    result = await service.submit(db, None, "alice", _order(), now=OPEN)
    assert result["status"] == "REFUSED" and "not logged in" in result["reason"]


async def test_stop_button_disables_once(world):
    db, _ = world
    await _prefs(db)
    assert await service.disable(db, "alice") is True
    assert await service.disable(db, "alice") is False
    assert (await service.submit(db, None, "alice", _order(), now=OPEN))["status"] == "REFUSED"


async def test_daily_loss_trips_the_kill_switch(world):
    db, _ = world
    await _prefs(db)
    await db["paper_trades"].insert_one({"user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "CLOSED",
                                         "strategy": "autopilot:chat", "via": "autopilot:chat", "realized_pnl": -1001.0, "venue": "paper",
                                         "exit_at": OPEN.replace(hour=10)})
    result = await service.submit(db, None, "alice", _order(), now=OPEN)
    assert result["status"] == "REFUSED" and "loss limit" in result["reason"]


async def test_telegram_stop_callback(monkeypatch):
    from backend.guardrails import telegram_bot

    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_one({"user_id": "alice", **PREFS})
    answer, edit = AsyncMock(), AsyncMock()
    monkeypatch.setattr(telegram_bot.telegram, "answer_callback", answer)
    monkeypatch.setattr(telegram_bot.telegram, "edit_html", edit)
    cb = {"id": "c", "data": "nt:autopilot:off", "message": {"message_id": 9, "text": "🤖 AI bought 2 INFY"}}
    await telegram_bot._callback(db, None, "alice", 42, "tok", cb)
    assert "stopped" in edit.await_args.args[2].lower()
    await telegram_bot._callback(db, None, "alice", 42, "tok", cb)
    assert "already off" in answer.await_args.args[1].lower()


async def test_chat_order_for_the_ai_account_goes_through_the_autopilot(world, monkeypatch):
    from backend.chat import actions
    from backend.instruments.master import InstrumentMaster
    from backend.instruments.models import Instrument

    db, sent = world
    await _prefs(db)
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="INFY", name="INFOSYS", instrument_token=1, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)])
    monkeypatch.setattr(service, "in_session", lambda now: True)
    tools = {t.name: t for t in actions.action_tools(db, None, "alice", "buy 2 infy on the AI account")}
    out = await tools["propose_order"].ainvoke({"symbol": "INFY", "side": "BUY", "quantity": 2, "account": "ai"})
    # A card, never an order on the model's word: the agent also reads news text.
    assert out.startswith("ACTION_CARD:")
    assert await db["paper_trades"].count_documents({}) == 0
    card = json.loads(out[len("ACTION_CARD:"):])
    done = await actions.confirm(db, None, None, "alice", card["id"])
    assert "bought 2 INFY" in done["result"]
    assert await db["paper_trades"].count_documents({"strategy": "autopilot:chat", "via": "autopilot:chat"}) == 1


async def test_live_mode_places_on_the_ai_adapter_only(world, monkeypatch):
    from backend.brokers.protocol import BrokerSessionState

    db, sent = world
    await _prefs(db, autopilot_live=True)
    calls = []

    class _Kite:
        async def state(self):
            return BrokerSessionState.ACTIVE

    kite = _Kite()

    async def ai_only(user_id, role, credentials, redis=None, roles=None, get_adapter=None):
        assert role == "ai"
        return kite

    async def live(order, ledger, adapter, orders, strategy_name="", reason=None, role="mine", owner=None):
        # The reconciler needs to know this order is on the AI broker, owned by the user.
        assert (role, owner) == ("ai", "alice")
        calls.append((adapter, order.product, order.strategy_name))
        return order, "COMPLETE", float(order.quantity)

    monkeypatch.setattr(service, "adapter_for", ai_only)
    monkeypatch.setattr("backend.suggestions.service.execute_live_order", live)
    result = await service.submit(db, None, "alice", _order(qty=2), now=OPEN)
    assert result["status"] == "FILLED" and result["mode"] == "live"
    assert calls == [(kite, "CNC", "autopilot:chat")]
    assert sent[0].startswith("🤖 AI bought 2 INFY on the AI account at")



@pytest.mark.parametrize("broker_status", ["REJECTED", "CANCELLED"])
async def test_live_order_the_broker_rejects_is_failed_not_sent(world, monkeypatch, broker_status):
    """Nothing filled and the broker said no: not held, not deployed, not an entry today."""
    db, sent = world
    await _prefs(db, autopilot_live=True)

    async def ai_only(user_id, role, credentials, redis=None, roles=None, get_adapter=None):
        return object()

    async def live(order, ledger, adapter, orders, strategy_name="", reason=None, role="mine", owner=None):
        return order, broker_status, 0.0

    monkeypatch.setattr(service, "adapter_for", ai_only)
    monkeypatch.setattr("backend.suggestions.service.execute_live_order", live)
    result = await service.submit(db, None, "alice", _order(qty=2), now=OPEN)
    assert result["status"] == "FAILED" and broker_status.lower() in result["reason"]
    assert result["broker_status"] == broker_status
    assert await db["autopilot_log"].count_documents({"status": "SENT"}) == 0
    state = await service._state(db, "alice", {**PREFS, "autopilot_live": True}, "live", OPEN)
    assert state.held == {} and state.deployed == 0 and state.entries_today == 0
    assert not sent[0].startswith("🤖 AI bought")


async def test_parallel_orders_cannot_exceed_capital_or_trades(world, monkeypatch):
    import asyncio

    db, _ = world
    await _prefs(db)
    symbols = ["INFY", "TCS", "HDFCBANK", "ICICIBANK", "SBIN", "ITC"]
    results = await asyncio.gather(*(service.submit(db, None, "alice", _order(symbol=s, qty=5), now=OPEN)
                                     for s in symbols))  # 6 x ₹5,000 vs ₹25,000 capital, 5 trades/day
    assert sum(r["status"] == "FILLED" for r in results) == 5


async def test_a_sent_but_unfilled_live_order_still_counts(world, monkeypatch):
    db, _ = world
    await _prefs(db)
    await db["autopilot_log"].insert_one({"user_id": "alice", "at": OPEN.replace(hour=10), "status": "SENT",
                                          "side": "BUY", "symbol": "INFY", "quantity": 5, "price": 1000.0,
                                          "product": "CNC", "source": "chat", "reason": "x"})
    again = await service.submit(db, None, "alice", _order(symbol="INFY", qty=1), now=OPEN)
    assert again["status"] == "REFUSED" and "already holding" in again["reason"]


async def test_a_sent_order_reconcile_booked_is_deployed_once(world):
    db, _ = world
    await _prefs(db)
    await db["autopilot_log"].insert_one({"user_id": "alice", "at": OPEN.replace(hour=10), "status": "SENT",
                                          "side": "BUY", "symbol": "INFY", "quantity": 5, "price": 1000.0,
                                          "product": "CNC", "source": "chat", "reason": "x", "order_id": "o1"})
    await db["live_orders"].insert_one({"_id": "o1", "status": "FILLED", "filled_quantity": 5.0})
    await db["paper_trades"].insert_one({"user_id": "alice:autopilot", "symbol": "INFY", "side": "BUY",
                                         "status": "OPEN", "quantity": 5, "entry_price": 1000.0,
                                         "via": "autopilot:chat", "venue": "live"})
    state = await service._state(db, "alice", PREFS, "live", OPEN)
    assert state.deployed == 5_000.0 and state.held == {"INFY": (5, "CNC")}


async def test_a_sent_order_the_broker_later_rejected_is_not_held(world):
    db, _ = world
    await _prefs(db)
    await db["autopilot_log"].insert_one({"user_id": "alice", "at": OPEN.replace(hour=10), "status": "SENT",
                                          "side": "BUY", "symbol": "INFY", "quantity": 5, "price": 1000.0,
                                          "product": "MIS", "source": "chat", "reason": "x", "order_id": "o1"})
    await db["live_orders"].insert_one({"_id": "o1", "status": "REJECTED", "filled_quantity": 0.0})
    state = await service._state(db, "alice", PREFS, "live", OPEN)
    assert state.deployed == 0 and state.held == {}


async def test_a_live_order_still_pending_logs_its_order_id(world, monkeypatch):
    db, _ = world
    await _prefs(db, autopilot_live=True)

    async def ai_only(user_id, role, credentials, redis=None, roles=None, get_adapter=None):
        return object()

    async def live(order, ledger, adapter, orders, strategy_name="", reason=None, role="mine", owner=None):
        await db["live_orders"].insert_one({"_id": order.id, "status": "SUBMITTED", "filled_quantity": 0.0})
        return order, "SUBMITTED", 0.0

    monkeypatch.setattr(service, "adapter_for", ai_only)
    monkeypatch.setattr("backend.suggestions.service.execute_live_order", live)
    assert (await service.submit(db, None, "alice", _order(qty=2), now=OPEN))["status"] == "SENT"
    row = await db["autopilot_log"].find_one({"status": "SENT"})
    assert await db["live_orders"].find_one({"_id": row["order_id"]}) is not None
    state = await service._state(db, "alice", {**PREFS, "autopilot_live": True}, "live", OPEN)
    assert state.deployed == 2_000.0 and state.held == {"INFY": (2, "CNC")}


async def test_paper_autopilot_trades_in_the_practice_book_tagged(world):
    db, _ = world
    await _prefs(db)
    await service.submit(db, None, "alice", _order(qty=2), now=OPEN)
    assert await db["paper_trades"].count_documents({"user_id": "alice", "strategy": "autopilot:chat", "via": "autopilot:chat"}) == 1
    assert await db["paper_trades"].count_documents({"user_id": "alice:autopilot"}) == 0


async def test_the_engines_practice_trades_do_not_count_against_the_autopilot(world):
    """Same book, but the fence counts only autopilot-tagged trades, and never
    buys into a symbol the engine holds (one owner per open position)."""
    db, _ = world
    await _prefs(db)
    await db["paper_trades"].insert_many([
        {"user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "OPEN", "quantity": 100,
         "entry_price": 1000.0, "strategy": "orb_breakout", "venue": "paper"},
        {"user_id": "alice", "symbol": "SBIN", "side": "BUY", "status": "CLOSED", "realized_pnl": -5000.0,
         "strategy": "orb_breakout", "venue": "paper", "exit_at": OPEN.replace(hour=10)},
    ])
    assert (await service.submit(db, None, "alice", _order(qty=2), now=OPEN))["status"] == "FILLED"
    refused = await service.submit(db, None, "alice", _order(symbol="TCS"), now=OPEN)
    assert refused["status"] == "REFUSED" and "paper engine already holds" in refused["reason"]


async def test_venue_must_match_the_autopilot_mode(world, monkeypatch):
    from backend.chat import actions
    from backend.instruments.master import InstrumentMaster
    from backend.instruments.models import Instrument

    db, _ = world
    await _prefs(db, autopilot_live=True)
    await InstrumentMaster(db).upsert_many([Instrument(
        exchange="NSE", tradingsymbol="INFY", name="INFOSYS", instrument_token=1, exchange_token=1,
        instrument_type="EQ", segment="NSE", lot_size=1, tick_size=0.05)])
    tools = {t.name: t for t in actions.action_tools(db, None, "alice", "buy")}
    out = await tools["propose_order"].ainvoke({"symbol": "INFY", "side": "BUY", "quantity": 1, "account": "ai"})
    assert "live" in out.lower() and await db["autopilot_log"].count_documents({}) == 0


async def test_autopilot_exits_hit_stop_through_the_fence(world, monkeypatch):
    db, sent = world
    await _prefs(db)
    await db["suggestions"].insert_one({"id": "s1", "user_id": "alice", "symbol": "INFY", "stop": 1100.0,
                                        "target": 1300.0})
    await service.submit(db, None, "alice", _order(qty=2, source="engine"), now=OPEN, suggestion_id="s1")
    closed = await service.check_exits(db, None, "alice", now=OPEN)  # mark 1000 <= stop 1100
    assert [c["symbol"] for c in closed] == ["INFY"]
    open_left = await db["paper_trades"].count_documents({"user_id": "alice", "status": "OPEN"})
    assert open_left == 0


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, nx=False, px=None, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)


async def test_lock_release_never_deletes_another_workers_lock(world, monkeypatch):
    """The 30s lock expired mid-order and another worker took it: releasing
    ours must leave theirs in place."""
    db, _ = world
    await _prefs(db)
    redis = _Redis()
    real = service._submit

    async def slow_submit(*args, **kw):
        redis.kv["autopilot:lock:alice"] = "other-worker"  # ours expired; theirs now
        return await real(*args, **kw)

    monkeypatch.setattr(service, "_submit", slow_submit)
    await service.submit(db, redis, "alice", _order(qty=1), now=OPEN)
    assert redis.kv.get("autopilot:lock:alice") == "other-worker"


@pytest.mark.parametrize("order,price,state,prefs,refusal", [
    (_order(), 100.0, _state(event_soon=True), PREFS, "economic event"),
    (_order(side=Side.SELL), 100.0, _state(event_soon=True, regime="risk_off", held={"INFY": (1, "CNC")}), PREFS, None),
    (_order(qty=3), 1000.0, _state(regime="risk_off"), PREFS, "halved"),             # cap 2,500 while risk-off
    (_order(qty=2), 1000.0, _state(regime="risk_off"), PREFS, None),
    (_order(qty=5), 1000.0, _state(regime="neutral"), PREFS, None),
    (_order(source="news"), 100.0, _state(), PREFS, "News-triggered trades are off"),
    (_order(source="news"), 100.0, _state(), {**PREFS, "autopilot_news": True}, None),
    (_order(source="news"), 100.0, _state(regime="risk_off"), {**PREFS, "autopilot_news": True}, "risk-off"),
    (_order(source="news"), 100.0, _state(news_today=3), {**PREFS, "autopilot_news": True}, "news-triggered trades today"),
])
def test_fence_market_backdrop_only_tightens(order, price, state, prefs, refusal):
    result = fence.check(order, price, state, prefs)
    assert result is None if refusal is None else (result and refusal in result)


async def test_max_hold_exit_paper_and_autopilot(world):
    """Held max_hold_days trading days, between stop and target: both books sell, reason "max hold"."""
    from backend.engine.persistence import LedgerStore
    from backend.suggestions import exits
    from backend.suggestions.service import execute_suggestion

    db, _ = world
    await _prefs(db)
    swing = {"stop": 900.0, "target": 1300.0, "max_hold_days": 3}
    # autopilot: entered Tue 6 Oct; Thu 8 Oct is 2 trading days, Fri 9 Oct is 3.
    await db["suggestions"].insert_one({"id": "s1", "user_id": "alice", "symbol": "INFY", **swing})
    await service.submit(db, None, "alice", _order(qty=2, source="engine"), now=OPEN, suggestion_id="s1")
    assert await service.check_exits(db, None, "alice", now=OPEN + timedelta(days=2)) == []
    closed = await service.check_exits(db, None, "alice", now=OPEN.replace(hour=15, minute=20) + timedelta(days=3))
    assert [(c["symbol"], c["reason"]) for c in closed] == [("INFY", "max hold")]

    # The user's own account (an approved proposal): the same rule, as an alert.
    suggestion = {"id": "s2", "user_id": "alice", "symbol": "TCS", "side": "BUY", "mode": "LONGTERM", "quantity": 1.0,
                  "strategy": "swing", "option_contract": None, **swing}
    await db["suggestions"].insert_one(dict(suggestion))
    await execute_suggestion(suggestion, LedgerStore(db, user_id="alice:mine"), price=1000.0, now=OPEN)

    async def marks(db_, symbols):
        return {s: 1000.0 for s in symbols}

    assert await exits.check_exits(db, "alice", now=OPEN + timedelta(days=2), marks_fn=marks) == []
    closed = await exits.check_exits(db, "alice", now=OPEN.replace(hour=15, minute=20) + timedelta(days=3), marks_fn=marks)
    assert [(c["symbol"], c["reason"]) for c in closed] == [("TCS", "max hold")]


async def test_an_autopilot_trade_counts_for_the_strategy_whose_idea_it_was(world):
    # Tagged "autopilot:engine", the paper gate never credited the strategy,
    # so nothing could ever earn real money (Phase 19.C).
    
    from backend.risk.paper_gate import paper_records

    db, _ = world
    await _prefs(db)
    order = replace(_order(qty=2), source="engine", strategy="orb_breakout")
    await service.submit(db, None, "alice", order, now=OPEN)
    await service.submit(db, None, "alice", replace(order, side=Side.SELL), now=OPEN)

    (trade,) = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)
    assert trade["strategy"] == "orb_breakout" and trade["via"] == "autopilot:engine"
    checks = (await paper_records(db, "alice", ["orb_breakout"], 25_000.0))["orb_breakout"]["checks"]
    assert next(c for c in checks if c["rule"] == "trades")["have"] == 1



async def test_intraday_positions_square_off_from_315_even_with_the_autopilot_off(world):
    from dataclasses import replace

    db, _ = world
    await _prefs(db)
    await service.submit(db, None, "alice", replace(_order(qty=2, product="MIS"), source="engine", strategy="orb"), now=OPEN)
    await db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"autopilot_enabled": False}})

    assert await service.check_exits(db, None, "alice", now=OPEN) == []  # 11:00: nothing yet
    closed = await service.check_exits(db, None, "alice", now=OPEN.replace(hour=15, minute=16))
    assert [c["reason"] for c in closed] == ["square-off"]
    (trade,) = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)
    assert trade["status"] == "CLOSED" and trade["strategy"] == "orb"


async def test_a_paper_fill_reaches_the_live_socket(world, monkeypatch):
    """Open AI pages refresh on these; a ledger without on_change left them stale."""
    db, _ = world
    await _prefs(db)
    published = []

    async def publish(user_id, topic, event, data):
        published.append((user_id, topic, event))

    monkeypatch.setattr(service.hub, "publish", publish)
    await service.submit(db, None, "alice", _order(), now=OPEN)
    assert ("alice", "trades", "changed") in published
    assert ("alice", "autopilot", "logged") in published


async def test_the_autopilot_skips_ideas_the_open_has_already_broken(world, monkeypatch):
    from backend.engine import autorun
    from backend.suggestions.store import SuggestionStore

    db, _ = world
    await _prefs(db)

    async def marks(db_, symbols, **_):
        return {s: 1000.0 for s in symbols}

    monkeypatch.setattr("backend.marks.mark_prices", marks)
    base = {"user_id": "alice", "side": "BUY", "mode": "LONGTERM", "quantity": 4, "status": "PENDING",
            "strategy": "orb_breakout", "score": {"final": 0.6}}
    await db["suggestions"].insert_many([
        {**base, "id": "gap", "symbol": "INFY", "entry_ref": 1050.0, "stop": 1010.0},   # opened under its stop
        {**base, "id": "chase", "symbol": "TCS", "entry_ref": 900.0, "stop": 850.0},    # 11% past its entry
        {**base, "id": "ok", "symbol": "HDFCBANK", "entry_ref": 990.0, "stop": 950.0},
    ])
    pending = await SuggestionStore(db).list("alice", status="PENDING")
    await autorun._autopilot_proposals(db, None, SuggestionStore(db), "alice", pending, OPEN)

    taken = {d["id"]: d.get("ai_order") for d in await db["suggestions"].find({}).to_list(None)}
    assert taken == {"gap": None, "chase": None, "ok": "FILLED"}


def test_an_entry_whose_expected_gain_cannot_pay_its_round_trip_is_refused():
    """2026-10-23: ₹3,000 lots cost ~0.8% a round trip; a pullback pick expected ~0%."""
    small = AutopilotOrder(symbol="INFY", side=Side.BUY, quantity=2, product="CNC", source="picks", reason="t",
                           context={"expected_return": 0.002})
    assert "too small to pay for itself" in fence.check(small, 1500.0, _state(), PREFS)
    ok = AutopilotOrder(symbol="INFY", side=Side.BUY, quantity=2, product="CNC", source="picks", reason="t",
                        context={"expected_return": 0.04})
    assert fence.check(ok, 1500.0, _state(), PREFS) is None
    assert fence.check(_order(qty=2), 1500.0, _state(), PREFS) is None  # says nothing: no rule
    cost = round_trip_cost(1500.0, 2, "CNC")
    assert 3000 * 0.006 < cost < 3000 * 0.012  # charges + DP + 2 x 10 bps on a ₹3,000 lot


@pytest.mark.parametrize("strategy", ["analyst_verdict", "mean_reversion", "built:abc"])
def test_parked_strategy_entries_are_refused_but_exits_are_not(strategy):
    buy = AutopilotOrder(symbol="INFY", side=Side.BUY, quantity=1, product="CNC", source="engine", reason="t", strategy=strategy)
    assert "parked" in fence.check(buy, 100.0, _state(), PREFS)
    sell = AutopilotOrder(symbol="INFY", side=Side.SELL, quantity=1, product="CNC", source="engine", reason="t", strategy=strategy)
    assert fence.check(sell, 100.0, _state(held={"INFY": (1, "CNC")}), PREFS) is None


def test_a_paused_strategy_cannot_enter_but_can_exit():
    paused = _state(paused=frozenset({"picks:pullback"}), held={"INFY": (1, "CNC")})
    buy = AutopilotOrder(symbol="INFY", side=Side.BUY, quantity=1, product="CNC", source="picks", reason="t",
                         strategy="picks:pullback")
    assert "paused" in fence.check(buy, 100.0, paused, PREFS)
    assert fence.check(replace(buy, side=Side.SELL), 100.0, paused, PREFS) is None


async def test_the_autopilot_refuses_a_dip_and_a_re_entry_after_a_stop(world, monkeypatch):
    """BHEL: entry_ref 427.35, stop 384.6, stopped 21 Oct at 417.55, bought again 22 Oct at 407.20."""
    from backend.engine import autorun
    from backend.suggestions.store import SuggestionStore

    db, _ = world
    await _prefs(db)
    prices = {"BHEL": 407.20, "INFY": 990.0, "WIPRO": 940.0, "TCS": 990.0}

    async def marks(db_, symbols, **_):
        return {s: prices[s] for s in symbols}

    monkeypatch.setattr("backend.marks.mark_prices", marks)
    base = {"user_id": "alice", "side": "BUY", "mode": "LONGTERM", "quantity": 4, "status": "PENDING",
            "strategy": "orb_breakout", "score": {"final": 0.6}}
    await db["suggestions"].insert_many([
        {**base, "id": "bhel", "symbol": "BHEL", "entry_ref": 427.35, "stop": 384.6},
        {**base, "id": "stopped", "symbol": "INFY", "entry_ref": 1000.0, "stop": 900.0},
        {**base, "id": "dip", "symbol": "WIPRO", "entry_ref": 1000.0, "stop": 900.0},  # 6% under, limit is 5%
        {**base, "id": "ok", "symbol": "TCS", "entry_ref": 1000.0, "stop": 900.0},
    ])
    for sym in ("BHEL", "INFY"):
        await db["paper_trades"].insert_one({"user_id": "alice", "symbol": sym, "status": "CLOSED",
                                             "realized_pnl": -50.0, "exit_at": OPEN - timedelta(days=1)})
    pending = await SuggestionStore(db).list("alice", status="PENDING")
    await autorun._autopilot_proposals(db, None, SuggestionStore(db), "alice", pending, OPEN)
    taken = {d["id"]: d.get("ai_order") for d in await db["suggestions"].find({}).to_list(None)}
    assert taken == {"bhel": None, "stopped": None, "dip": None, "ok": "FILLED"}


async def test_the_autopilot_quietly_leaves_ideas_outside_its_universe_to_the_user(world, monkeypatch):
    """SJVN, 16 refusals to 2026-10-23: a scan idea outside the Nifty 200 is the user's, not a fence refusal."""
    from backend.engine import autorun
    from backend.suggestions.store import SuggestionStore

    db, _ = world
    await _prefs(db)
    sent = []

    async def marks(db_, symbols, **_):
        return {s: 1000.0 for s in symbols}

    async def notify(db_, user_id, text, *a, **kw):
        sent.append(text)

    monkeypatch.setattr("backend.marks.mark_prices", marks)
    monkeypatch.setattr("backend.suggestions.notify.notify", notify)
    base = {"user_id": "alice", "side": "BUY", "mode": "LONGTERM", "quantity": 4, "status": "PENDING",
            "strategy": "orb_breakout", "score": {"final": 0.6}, "entry_ref": 990.0, "stop": 950.0}
    await db["suggestions"].insert_many([{**base, "id": "out", "symbol": "NOTANIFTY"},
                                         {**base, "id": "in", "symbol": "INFY"}])
    pending = await SuggestionStore(db).list("alice", status="PENDING")
    await autorun._autopilot_proposals(db, None, SuggestionStore(db), "alice", pending, OPEN)
    docs = {d["id"]: d for d in await db["suggestions"].find({}).to_list(None)}
    assert docs["in"]["ai_order"] == "FILLED"
    assert docs["out"].get("ai_order") is None and docs["out"]["status"] == "PENDING"  # still the user's idea
    assert sent and all("NOTANIFTY" not in t for t in sent)
    assert await db["autopilot_log"].count_documents({"symbol": "NOTANIFTY"}) == 0
