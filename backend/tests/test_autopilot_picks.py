"""The AI account trades Picks on paper (backend/autopilot/picks.py): bought
at the next session's morning pass, sold at the close of the horizon, sized
inside the fence, never on the user's own account, and live only once the
forward record passes and the owner says so."""

from datetime import datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import picks as trading, service
from backend.engine.session import IST
from backend.forecast.picks import MIN_FORWARD, live_refusal

SIGNAL = "2026-10-05"                                  # Monday's 16:00 pass
MORNING = datetime(2026, 10, 6, 9, 21, tzinfo=IST)     # Tuesday, first pass after the open
DUE = "2026-10-09"
PREFS = {"autopilot_enabled": True, "autopilot_live": False, "account_size": 25_000.0, "max_exposure": 25_000.0,
         "per_trade_cap": 5_000.0, "max_trades_per_day": 5, "daily_loss_limit": 1_000.0}


def _pick(symbol="INFY", date=SIGNAL, setup="momentum", excess=0.02, outcome=None):
    return {"_id": f"{date}:{setup}:{symbol}", "date": date, "symbol": symbol, "setup": setup, "label": "Momentum",
            "horizon": 3, "due_date": DUE, "p_up": 0.6, "p_beat_nifty": 0.55, "median_excess": excess,
            "strength": 1.0, "outcome": outcome}


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    sent, regime = [], {}

    async def notify(*a, **kw):
        sent.append(a)
        return True

    async def marks(db_, symbols, **_):
        return {s: 1000.0 for s in symbols}

    async def regime_now(redis):
        return regime

    monkeypatch.setattr(service, "_notify", notify)
    monkeypatch.setattr(service, "mark_prices", marks)
    monkeypatch.setattr(trading, "mark_prices", marks)
    monkeypatch.setattr(service, "regime_now", regime_now)
    return db, sent, regime


async def _setup(db, role="admin", **prefs):
    await db["users"].insert_one({"id": "alice", "role": role})
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"},
                                       **PREFS, **prefs})


async def _trades(db):
    return await db["paper_trades"].find({}).to_list(None)


async def test_a_pick_is_bought_at_the_next_morning_once_credited_to_its_setup(world):
    db, sent, _ = world
    await _setup(db)
    await db["picks"].insert_many([_pick(), _pick("TCS", date="2026-10-06")])  # TCS: today's, not yet
    results = await trading.enter(db, None, "alice", MORNING)
    assert [r["status"] for r in results] == ["FILLED"]
    [trade] = await _trades(db)
    assert trade["user_id"] == "alice" and trade["venue"] != "live"  # the AI account's paper book
    assert trade["strategy"] == "picks:momentum" and trade["via"] == "autopilot:picks"
    assert trade["context"]["pick_id"] == f"{SIGNAL}:momentum:INFY" and trade["mode"] == "LONGTERM"
    assert sent == []  # Picks never reach Telegram
    assert await trading.enter(db, None, "alice", MORNING) == []  # once per pick


async def test_only_admins_trade_picks(world):
    db, _, _ = world
    await _setup(db, role="user")
    await db["picks"].insert_one(_pick())
    assert await trading.enter(db, None, "alice", MORNING) == []
    assert await _trades(db) == []


async def test_a_pick_is_sold_at_the_close_of_its_horizon(world):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_pick())
    await trading.enter(db, None, "alice", MORNING)
    assert await trading.exit_due(db, None, "alice", datetime(2026, 10, 8, 15, 20, tzinfo=IST)) == []  # day before
    assert await trading.exit_due(db, None, "alice", datetime(2026, 10, 9, 14, 0, tzinfo=IST)) == []   # due, not the close
    [sold] = await trading.exit_due(db, None, "alice", datetime(2026, 10, 9, 15, 16, tzinfo=IST))
    assert sold["status"] == "FILLED"
    [trade] = await _trades(db)
    assert trade["status"] == "CLOSED" and trade["costs"] > 0


async def test_exits_run_even_with_the_autopilot_off_and_a_late_one_goes_at_once(world):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_pick())
    await trading.enter(db, None, "alice", MORNING)
    await db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"autopilot_enabled": False}})
    [sold] = await trading.exit_due(db, None, "alice", datetime(2026, 10, 12, 10, 0, tzinfo=IST))
    assert sold["status"] == "FILLED"


async def test_sizing_stays_inside_the_per_trade_cap_and_max_invested(world):
    db, _, regime = world
    await _setup(db, max_exposure=7_000.0)
    await db["picks"].insert_many([_pick("INFY", excess=0.03), _pick("TCS", excess=0.01)])
    results = await trading.enter(db, None, "alice", MORNING)
    assert results[0]["status"] == "FILLED" and results[1]["status"] == "REFUSED"
    assert "max invested" in results[1]["reason"]
    [trade] = await _trades(db)
    assert trade["symbol"] == "INFY" and trade["quantity"] == 5  # ₹5,000 cap / ₹1,000

    db2 = AsyncMongoMockClient()["other"]
    await _setup(db2)
    await db2["picks"].insert_one(_pick())
    regime["label"] = "risk_off"  # the cap halves
    await trading.enter(db2, None, "alice", MORNING)
    assert (await _trades(db2))[0]["quantity"] == 2


async def test_the_kill_switch_blocks_pick_entries(world):
    db, _, _ = world
    await _setup(db)
    await db["autopilot_state"].insert_one({"_id": "alice", "tripped_day": "2026-10-06"})
    await db["picks"].insert_one(_pick())
    [result] = await trading.enter(db, None, "alice", MORNING)
    assert result["status"] == "REFUSED" and "loss limit" in result["reason"]
    assert await _trades(db) == []


def _scored(n, won=True, net=0.02, nifty=0.01):
    return [_pick(symbol=f"S{i}", outcome={"won": won if i % 5 else not won, "net": net, "nifty": nifty,
                                                    "beat_nifty": net > nifty})
            for i in range(n)]


def test_live_needs_a_full_calibrated_record_that_beats_the_nifty():
    good = _scored(MIN_FORWARD)  # p_up 0.6, 80% won -> 20 points off
    assert "scored picks" in live_refusal(good[:-1])
    assert "calibration" in live_refusal(good)
    calibrated = [{**p, "outcome": {**p["outcome"], "won": i % 5 < 3}} for i, p in enumerate(good)]  # 60%
    assert live_refusal(calibrated) is None
    behind = [{**p, "outcome": {**p["outcome"], "nifty": 0.05}} for p in calibrated]
    assert "Nifty" in live_refusal(behind)


async def _record_passes(db):
    await db["picks"].insert_many([{**p, "date": "2026-01-01", "_id": f"old{i}",
                                    "outcome": {"won": i % 5 < 3, "net": 0.02, "nifty": 0.01, "beat_nifty": True}}
                                   for i, p in enumerate(_scored(MIN_FORWARD))])


async def test_live_is_refused_before_the_gate_and_without_the_pref(world, monkeypatch):
    db, _, _ = world

    async def no_live(*a, **kw):
        raise AssertionError("a pick must not reach a broker")

    monkeypatch.setattr(service, "adapter_for", no_live)
    await _setup(db, autopilot_live=True, picks_live=True)  # owner armed, record not there yet
    await db["picks"].insert_one(_pick())
    [result] = await trading.enter(db, None, "alice", MORNING)
    assert result["status"] == "FILLED" and result["mode"] == "paper"

    db2 = AsyncMongoMockClient()["other"]
    await _setup(db2, autopilot_live=True)  # record passes, picks_live off (the default)
    await _record_passes(db2)
    await db2["picks"].insert_one(_pick())
    [result] = await trading.enter(db2, None, "alice", MORNING)
    assert result["mode"] == "paper"


async def test_live_picks_go_to_the_ai_account_never_mine(world, monkeypatch):
    from backend.brokers.roles import RoleUnavailable

    db, _, _ = world
    roles = []

    async def ai_only(user_id, role, credentials, redis=None, **kw):
        roles.append(role)
        raise RoleUnavailable(role, "AI account not logged in.")  # and no fallback to another account

    monkeypatch.setattr(service, "adapter_for", ai_only)
    await _setup(db, autopilot_live=True, picks_live=True)
    await _record_passes(db)
    await db["picks"].insert_one(_pick())
    [result] = await trading.enter(db, None, "alice", MORNING)
    assert roles == ["ai"] and result["status"] == "REFUSED" and result["mode"] == "live"
    assert await _trades(db) == []
