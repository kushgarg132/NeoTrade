"""The fenced autopilot on the AI account: every order passes the fence or is
refused (logged, never retried), paper first, a one-tap stop on Telegram,
and it never touches the user's own account."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import fence, service
from backend.autopilot.fence import FenceState
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


def test_fence_refuses_everything_when_disabled():
    assert "off" in fence.check(_order(), 100.0, _state(), {**PREFS, "autopilot_enabled": False})


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
                                         "strategy": "autopilot:chat", "realized_pnl": -1001.0, "venue": "paper",
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
    assert not out.startswith("ACTION_CARD:") and "bought 2 INFY" in out
    assert await db["paper_trades"].count_documents({"strategy": "autopilot:chat"}) == 1


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


async def test_paper_autopilot_trades_in_the_practice_book_tagged(world):
    db, _ = world
    await _prefs(db)
    await service.submit(db, None, "alice", _order(qty=2), now=OPEN)
    assert await db["paper_trades"].count_documents({"user_id": "alice", "strategy": "autopilot:chat"}) == 1
    assert await db["paper_trades"].count_documents({"user_id": "alice:autopilot"}) == 0


async def test_the_engines_practice_trades_do_not_count_against_the_autopilot(world):
    """Same book, but the fence counts only autopilot-tagged trades, and never
    buys into a symbol the engine holds (one owner per open position)."""
    db, _ = world
    await _prefs(db)
    await db["paper_trades"].insert_many([
        {"user_id": "alice", "symbol": "TCS", "side": "BUY", "status": "OPEN", "quantity": 100,
         "entry_price": 1000.0, "strategy": "macd_crossover", "venue": "paper"},
        {"user_id": "alice", "symbol": "SBIN", "side": "BUY", "status": "CLOSED", "realized_pnl": -5000.0,
         "strategy": "macd_crossover", "venue": "paper", "exit_at": OPEN.replace(hour=10)},
    ])
    assert (await service.submit(db, None, "alice", _order(qty=2), now=OPEN))["status"] == "FILLED"
    refused = await service.submit(db, None, "alice", _order(symbol="TCS"), now=OPEN)
    assert refused["status"] == "REFUSED" and "Practice engine" in refused["reason"]


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

    # paper (the user's own approved proposal), same rule.
    suggestion = {"id": "s2", "user_id": "alice", "symbol": "TCS", "side": "BUY", "mode": "LONGTERM", "quantity": 1.0,
                  "strategy": "swing", "option_contract": None, **swing}
    await db["suggestions"].insert_one(dict(suggestion))
    await execute_suggestion(suggestion, LedgerStore(db, user_id="alice"), price=1000.0, now=OPEN)

    async def marks(db_, symbols):
        return {s: 1000.0 for s in symbols}

    assert await exits.check_exits(db, "alice", now=OPEN + timedelta(days=2), marks_fn=marks) == []
    closed = await exits.check_exits(db, "alice", now=OPEN.replace(hour=15, minute=20) + timedelta(days=3), marks_fn=marks)
    assert [(c["symbol"], c["reason"]) for c in closed] == [("TCS", "max hold")]
