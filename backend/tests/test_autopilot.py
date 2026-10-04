"""The fenced autopilot on the AI account: every order passes the fence or is
refused (logged, never retried), paper first, a one-tap stop on Telegram,
and it never touches the user's own account."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import fence, service
from backend.autopilot.fence import FenceState
from backend.autopilot.service import AutopilotOrder
from backend.core.models import Side
from backend.engine.session import IST

OPEN = datetime(2026, 10, 6, 11, 0, tzinfo=IST)
PREFS = {"autopilot_enabled": True, "autopilot_live": False, "autopilot_capital": 25_000.0,
         "autopilot_per_trade_cap": 5_000.0, "autopilot_max_trades_per_day": 5, "autopilot_daily_loss_limit": 1_000.0}


def _state(**kw):
    base = dict(deployed=0.0, entries_today=0, open_symbols=set(), kill_tripped=False, session_ok=True)
    return FenceState(**{**base, **kw})


def _order(symbol="INFY", side=Side.BUY, qty=1, product="CNC", source="chat"):
    return AutopilotOrder(symbol=symbol, side=side, quantity=qty, product=product, source=source, reason="test")


@pytest.mark.parametrize("order,price,state,refusal", [
    (_order(qty=5), 1000.0, _state(), None),                                  # exactly the per-trade cap
    (_order(qty=5), 1000.2, _state(), "per-trade cap"),
    (_order(qty=1), 1000.0, _state(deployed=24_000.0), None),                 # exactly fills capital
    (_order(qty=1), 1001.0, _state(deployed=24_000.0), "capital"),
    (_order(), 100.0, _state(entries_today=5), "trades today"),
    (_order(symbol="NOTANIFTY"), 100.0, _state(), "universe"),
    (_order(product="NRML"), 100.0, _state(), "NSE equity"),
    (_order(), 100.0, _state(kill_tripped=True), "loss limit"),
    (_order(), 100.0, _state(session_ok=False), "market"),
    (_order(), 100.0, _state(open_symbols={"INFY"}), "already holding"),
    (_order(side=Side.SELL, qty=50), 1000.0, _state(open_symbols={"INFY"}, deployed=25_000.0, entries_today=5), None),
])
def test_fence_limits(order, price, state, refusal):
    result = fence.check(order, price, state, PREFS)
    if refusal is None:
        assert result is None
    else:
        assert result and refusal in result


def test_fence_refuses_everything_when_disabled():
    assert "off" in fence.check(_order(), 100.0, _state(), {**PREFS, "autopilot_enabled": False})


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    sent = []

    async def notify(db_, user_id, text, stop_button=True):
        sent.append(text)
        return True

    async def marks(db_, symbols):
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
    trades = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)
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
