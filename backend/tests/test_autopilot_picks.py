"""Exits for the Picks trades the AI account still holds (backend/autopilot/picks.py):
sold at the close of the horizon, or at a tested stop/target; the forward record's live gate."""

from datetime import datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import picks as trading, service
from backend.engine.session import IST
from backend.core.models import Side
from backend.forecast.picks import MIN_FORWARD, levels, live_refusal

pytestmark = pytest.mark.usefixtures("lenient_fence")

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


def _study(levels_better=True, **grades):
    """picks_study doc: setup -> (adjusted excess, t); t >= 2 is grade A, t 0 is C. `levels_better`: the study
    found the stop/target exit beat the horizon close, so entries store the levels."""
    return {"_id": "latest", "setups": [{"setup": k, "adjusted": {"excess": e, "t": t, "edge": t >= 2},
                                         "levels_exit": {"better": levels_better}} for k, (e, t) in grades.items()]}


async def _setup(db, role="admin", study=None, **prefs):
    await db["picks_study"].insert_one(study or _study(momentum=(0.02, 3.0), reversal=(0.01, 3.0), weak=(-0.01, 0.0)))
    await db["users"].insert_one({"id": "alice", "role": role})
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"},
                                       **PREFS, **prefs})


async def _enter(db):
    """Opens each stored pick as the retired `picks.enter` did (2026-11-02: the autopilot buys only the rotation)."""
    use = trading._levels_tested(await db["picks_study"].find_one({"_id": "latest"}))
    for p in await db["picks"].find({}).to_list(None):
        lv = levels(p) if p["setup"] in use else None
        ctx = {"pick_id": p["_id"], "due_date": p["due_date"], "reason_codes": [p["setup"]]}
        if lv:
            ctx.update(entry_ref=p.get("entry_ref"), stop=lv.get("stop"), target=lv.get("target"))
        await service.submit(db, None, "alice", service.AutopilotOrder(
            symbol=p["symbol"], side=Side.BUY, quantity=4, product="CNC", source="picks", reason="test",
            strategy=f"picks:{p['setup']}", context=ctx), now=MORNING, quiet=True)


async def _trades(db):
    return await db["paper_trades"].find({}).to_list(None)


async def test_a_pick_is_sold_at_the_close_of_its_horizon(world):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_pick())
    await _enter(db)
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
    await _enter(db)
    await db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"autopilot_enabled": False}})
    [sold] = await trading.exit_due(db, None, "alice", datetime(2026, 10, 12, 10, 0, tzinfo=IST))
    assert sold["status"] == "FILLED"


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


def _leveled(symbol="INFY"):
    # Priced off a ₹1000 close: stop ₹950 (p10, tighter than 3 ATR ₹925), target ₹1150 (p90).
    return {**_pick(symbol), "entry_ref": 1000.0, "atr": 25.0,
            "expected": {"median": 0.08, "p10": -0.05, "p90": 0.15}}


def _mark(monkeypatch, price):
    async def marks(db_, symbols, **_):
        return {s: price for s in symbols}
    monkeypatch.setattr(service, "mark_prices", marks)
    monkeypatch.setattr(trading, "mark_prices", marks)


async def test_a_pick_sells_at_its_stop_or_target_before_the_horizon(world, monkeypatch):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_leveled())
    _mark(monkeypatch, 1010.0)  # filled ~₹1011 (10 bps slip): stop ~₹961, target ~₹1162
    await _enter(db)
    [trade] = await _trades(db)
    assert trade["context"]["stop"] == 950.0 and trade["context"]["target"] == 1150.0
    early = datetime(2026, 10, 7, 11, 0, tzinfo=IST)  # two days before the due date
    _mark(monkeypatch, 965.0)
    assert await trading.exit_due(db, None, "alice", early) == []  # above the fill-anchored stop
    _mark(monkeypatch, 955.0)  # above the stored ₹950, under the anchored ~₹961
    [sold] = await trading.exit_due(db, None, "alice", early)
    assert sold["status"] == "FILLED" and sold["why"] == "stop"


async def test_a_pick_takes_its_target(world, monkeypatch):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_leveled())
    await _enter(db)  # fixture mark ₹1000
    _mark(monkeypatch, 1165.0)
    [sold] = await trading.exit_due(db, None, "alice", datetime(2026, 10, 7, 11, 0, tzinfo=IST))
    assert sold["why"] == "target"


async def test_a_pick_without_levels_keeps_the_time_exit_only(world, monkeypatch):
    db, _, _ = world
    await _setup(db)
    await db["picks"].insert_one(_pick())
    await _enter(db)
    _mark(monkeypatch, 1.0)
    assert await trading.exit_due(db, None, "alice", datetime(2026, 10, 7, 11, 0, tzinfo=IST)) == []


async def test_levels_are_traded_only_where_the_study_found_they_beat_the_horizon_exit(world, monkeypatch):
    db, _, _ = world
    await _setup(db, study=_study(levels_better=False, momentum=(0.02, 3.0)))
    await db["picks"].insert_one(_leveled())
    await _enter(db)
    [trade] = await _trades(db)
    assert "stop" not in trade["context"] and "target" not in trade["context"]
    _mark(monkeypatch, 900.0)  # far under the untraded stop: held to the horizon, as the study graded it
    assert await trading.exit_due(db, None, "alice", datetime(2026, 10, 7, 11, 0, tzinfo=IST)) == []


async def test_an_open_trade_drops_its_stored_levels_once_the_study_finds_they_lose(world, monkeypatch):
    db, _, _ = world
    await _setup(db)                                      # levels better: stored on entry
    await db["picks"].insert_one(_leveled())
    await _enter(db)
    await db["picks_study"].replace_one({"_id": "latest"}, _study(levels_better=False, momentum=(0.02, 3.0)))
    _mark(monkeypatch, 900.0)
    assert await trading.exit_due(db, None, "alice", datetime(2026, 10, 7, 11, 0, tzinfo=IST)) == []
