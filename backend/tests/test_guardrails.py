"""Guardrails: the user's own limits checked against their real broker
activity, alerted once per breach, and a daily-loss breach halting the engine."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from mongomock_motor import AsyncMongoMockClient

from backend.brokers.trades import parse_ist
from backend.core.models import BrokerTrade, Side
from backend.guardrails import monitor
from backend.guardrails.rules import evaluate
from backend.guardrails.store import GuardrailStore
from backend.journal.store import JournalStore
from backend.risk.kill_switch import KillSwitchStore

PREFS = {"daily_loss_limit": 10_000, "max_trades_per_day": 0, "cooldown_after_losses": 0, "cooldown_minutes": 30}


def _ist(hh, mm):
    return parse_ist(datetime(2026, 9, 1, hh, mm))


def _trip(i, hh, mm, pnl, minutes=5, symbol="SBIN"):
    opened = _ist(hh, mm)
    return {"id": f"t{i}", "symbol": symbol, "opened_at": opened,
            "closed_at": opened + timedelta(minutes=minutes) if pnl is not None else None, "pnl": pnl}


def _rules(breaches):
    return [b["rule"] for b in breaches]


def test_daily_loss_trips_at_the_limit_not_before():
    assert evaluate([], -9_999.0, PREFS) == []
    [breach] = evaluate([], -10_000.0, PREFS)
    assert breach["key"] == "daily_loss"
    assert "₹10,000" in breach["detail"]


def test_zero_turns_every_rule_off():
    trips = [_trip(i, 10, i, -1.0) for i in range(10)]
    assert evaluate(trips, -1e9, {**PREFS, "daily_loss_limit": 0}) == []


def test_trade_count_breaches_only_past_the_limit():
    prefs = {**PREFS, "max_trades_per_day": 3}
    assert evaluate([_trip(i, 10, i * 10, 1.0) for i in range(3)], 0, prefs) == []
    [breach] = evaluate([_trip(i, 10, i * 10, 1.0) for i in range(4)], 0, prefs)
    assert breach["key"] == "max_trades"


def test_cooldown_start_and_broken():
    prefs = {**PREFS, "cooldown_after_losses": 2, "cooldown_minutes": 30}
    trips = [
        _trip(1, 10, 0, -100.0),   # closes 10:05
        _trip(2, 10, 10, -100.0),  # closes 10:15 -> cooldown until 10:45
        _trip(3, 10, 20, 50.0, symbol="TCS"),  # opened in cooldown
        _trip(4, 10, 50, 50.0),    # after cooldown, fine
    ]
    breaches = evaluate(trips, 0, prefs)
    assert [b["key"] for b in breaches] == ["cooldown_start:t2", "cooldown_broken:t3"]
    assert "10:45" in breaches[0]["detail"]
    assert "TCS at 10:20" in breaches[1]["detail"]


def test_a_win_resets_the_streak():
    prefs = {**PREFS, "cooldown_after_losses": 2}
    trips = [_trip(1, 10, 0, -1.0), _trip(2, 10, 10, 1.0), _trip(3, 10, 20, -1.0)]
    assert evaluate(trips, 0, prefs) == []


def test_session_window():
    assert monitor.in_session(_ist(9, 15))
    assert monitor.in_session(_ist(15, 35))
    assert not monitor.in_session(_ist(9, 14))
    assert not monitor.in_session(parse_ist(datetime(2026, 9, 6, 11, 0)))  # Sunday


async def test_check_user_alerts_once_and_trips_the_kill_switch(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    await JournalStore(db).add_trades("alice", "kite", [
        BrokerTrade(trade_id="1", symbol="SBIN", side=Side.BUY, quantity=100, price=800.0, traded_at=_ist(10, 0)),
        BrokerTrade(trade_id="2", symbol="SBIN", side=Side.SELL, quantity=100, price=690.0, traded_at=_ist(10, 30)),
    ], source="sync")
    monkeypatch.setattr(monitor, "sync_user_trades", AsyncMock(return_value={
        "imported": 0, "brokers": ["kite"], "failed": [], "day_pnl": -11_000.0}))
    publish = AsyncMock()
    monkeypatch.setattr(monitor.hub, "publish", publish)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor.telegram, "send", send)
    monkeypatch.setattr(monitor.telegram, "configured", lambda: True)  # the server bot
    await GuardrailStore(db).set_telegram_chat("alice", 42)

    prefs = {**PREFS, "user_id": "alice", "max_trades_per_day": 0}
    now = _ist(10, 31)
    fresh = await monitor.check_user(db, None, None, prefs, now)

    assert _rules(fresh) == ["daily_loss"]
    assert await KillSwitchStore(db).is_tripped("alice", now.astimezone(monitor.IST).date())
    publish.assert_awaited_once()
    send.assert_awaited_once()
    assert send.await_args.args[0] == 42

    assert await monitor.check_user(db, None, None, prefs, now) == []  # no repeat alert
    events = await GuardrailStore(db).events_for("alice", now.astimezone(monitor.IST).date())
    assert [e["rule"] for e in events] == ["daily_loss"]


async def test_check_user_does_nothing_without_a_connected_broker(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(monitor, "sync_user_trades", AsyncMock(return_value={
        "imported": 0, "brokers": [], "failed": [], "day_pnl": 0.0}))
    assert await monitor.check_user(db, None, None, {**PREFS, "user_id": "alice"}, _ist(10, 0)) == []


async def test_run_tick_skips_when_another_worker_holds_the_lock(monkeypatch):
    redis = MagicMock()
    redis.set = AsyncMock(return_value=False)
    check = AsyncMock()
    monkeypatch.setattr(monitor, "check_user", check)
    assert await monitor.run_tick(AsyncMongoMockClient()["test_db"], redis, now=_ist(10, 0)) == 0
    check.assert_not_awaited()


async def test_run_tick_only_checks_opted_in_users(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_many([
        {"user_id": "alice", "guardrails_enabled": True},
        {"user_id": "bob", "guardrails_enabled": False},
    ])
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    check = AsyncMock()
    monkeypatch.setattr(monitor, "check_user", check)
    monkeypatch.setattr(monitor, "fernet_from_settings", lambda: None)
    assert await monitor.run_tick(db, redis, now=_ist(10, 0)) == 1
    assert check.await_args.args[3]["user_id"] == "alice"
    assert await monitor.run_tick(db, redis, now=_ist(16, 0)) == 0  # after the session


async def test_a_users_own_bot_is_stored_encrypted_and_used_for_their_alerts(monkeypatch):
    from cryptography.fernet import Fernet
    from backend.guardrails import store as store_module, telegram

    key = Fernet(Fernet.generate_key())
    monkeypatch.setattr(store_module, "fernet_from_settings", lambda: key)
    monkeypatch.setattr(telegram, "configured", lambda: False)  # no server bot at all
    sent = []

    async def send(chat_id, text, token=None):
        sent.append((chat_id, token))
        return True
    monkeypatch.setattr(telegram, "send", send)

    db = AsyncMongoMockClient()["test_db"]
    store = GuardrailStore(db)
    assert await telegram.alert(db, "alice", "x") is False  # nothing linked, no bot

    await store.set_telegram_bot("alice", "123456:ABCdef_ghi-jkl", "alice_alerts_bot")
    raw = await db["alert_channels"].find_one({"_id": "alice"})
    assert "ABCdef" not in raw["telegram_bot_token"]  # encrypted at rest
    await store.set_telegram_chat("alice", 77)

    assert await telegram.alert(db, "alice", "hello") is True
    assert sent == [(77, "123456:ABCdef_ghi-jkl")]
    assert (await store.telegram_bot("alice"))["username"] == "alice_alerts_bot"

    await store.set_telegram_bot("alice", "999999:Other_bot_token")  # a new bot unlinks the old chat
    assert await store.telegram_chat("alice") is None


async def test_guardrails_watch_only_the_users_own_account(monkeypatch):
    # The AI account's trades and P&L are the autopilot's, never the user's guardrails.
    db = AsyncMongoMockClient()["test_db"]
    await JournalStore(db).add_trades("alice", "kite", [
        BrokerTrade(trade_id="1", symbol="SBIN", side=Side.BUY, quantity=100, price=800.0, traded_at=_ist(10, 0)),
        BrokerTrade(trade_id="2", symbol="SBIN", side=Side.SELL, quantity=100, price=690.0, traded_at=_ist(10, 30)),
    ], source="sync")
    sync = AsyncMock(return_value={"imported": 0, "brokers": ["upstox"], "failed": [], "day_pnl": 0.0})
    monkeypatch.setattr(monitor, "sync_user_trades", sync)
    monkeypatch.setattr(monitor.hub, "publish", AsyncMock())

    prefs = {**PREFS, "user_id": "alice", "max_trades_per_day": 1, "broker_roles": {"kite": "ai", "upstox": "mine"}}
    assert await monitor.check_user(db, None, None, prefs, _ist(10, 31)) == []
    assert sync.await_args.kwargs["skip"] == {"kite"}


async def test_sync_skips_the_brokers_it_is_told_to(monkeypatch):
    from backend.journal import sync as journal_sync

    adapter = MagicMock()
    adapter.state = AsyncMock(return_value=monitor.BrokerSessionState.ACTIVE)
    adapter.get_trades = AsyncMock(return_value=[])
    adapter.get_positions = AsyncMock(return_value={})
    monkeypatch.setattr(journal_sync, "BROKERS", {"kite": None, "upstox": None})
    get = AsyncMock(return_value=adapter)
    monkeypatch.setattr(journal_sync, "get_broker_adapter", get)
    db = AsyncMongoMockClient()["test_db"]
    result = await journal_sync.sync_user_trades(db, None, None, "alice", include_pnl=True, skip={"kite"})
    assert result["brokers"] == ["upstox"]
    assert [c.args[0] for c in get.await_args_list] == ["upstox"]
