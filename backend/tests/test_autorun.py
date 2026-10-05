"""The daily intraday paper run starts itself at the open, exactly once
across workers, comes back after a deploy, respects a manual stop, and
stops at the close."""

import asyncio
from datetime import datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine import autorun
from backend.engine.session import IST
from backend.routers import trading
from backend.runs import RunStore

MONDAY_10AM = datetime(2026, 9, 28, 10, 0, tzinfo=IST)
MONDAY_EVENING = datetime(2026, 9, 28, 15, 31, tzinfo=IST)
SUNDAY_10AM = datetime(2026, 9, 27, 10, 0, tzinfo=IST)


class _Redis:
    """The three calls autorun makes, with NX/XX semantics (TTL ignored)."""

    def __init__(self):
        self.data = {}

    async def exists(self, key):
        return 1 if key in self.data else 0

    async def set(self, key, value, nx=False, xx=False, px=None):
        if (nx and key in self.data) or (xx and key not in self.data):
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


async def _forever():
    await asyncio.Event().wait()


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(autorun, "_LOCAL", {})
    monkeypatch.setattr(autorun, "_TOKEN", "worker-a")
    launched = []

    async def launch(user_id, mode, universe, poll, runs, origin):
        run_id = f"run-{len(launched) + 1}"
        await runs.create(run_id=run_id, user_id=user_id, mode=mode, universe=universe,
                          params={"origin": origin})
        # started_at must fall on the simulated trading day
        await runs.collection.update_one({"run_id": run_id}, {"$set": {"started_at": MONDAY_10AM}})
        trading._RUNS[run_id] = asyncio.get_running_loop().create_task(_forever())
        launched.append((user_id, mode, origin))
        return run_id

    async def enable(user_id="alice"):
        await db["user_prefs"].insert_one({"user_id": user_id, "auto_paper_intraday": True})

    redis = _Redis()
    from backend.runs import ALIVE_KEY, BOOT_ID
    redis.data[ALIVE_KEY.format(BOOT_ID)] = "1"  # this worker's heartbeat (server.py)
    yield type("W", (), {"db": db, "redis": redis, "launch": launch, "launched": launched, "enable": enable})
    for task in list(trading._RUNS.values()):
        task.cancel()
    trading._RUNS.clear()


def _tick(w, now):
    return autorun.tick(w.db, w.redis, now=now, launch=w.launch)


@pytest.mark.asyncio
async def test_starts_one_paper_intraday_run_in_session_then_only_renews(world):
    await world.enable()

    assert (await _tick(world, SUNDAY_10AM))["started"] == []
    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice"]
    assert (await _tick(world, MONDAY_10AM))["renewed"] == ["alice"]
    assert world.launched == [("alice", "INTRADAY", "auto")]
    assert world.redis.data["autorun:alice"] == "worker-a"


@pytest.mark.asyncio
async def test_users_who_did_not_opt_in_are_left_alone(world):
    await world.db["user_prefs"].insert_one({"user_id": "bob", "auto_paper_intraday": False})
    assert (await _tick(world, MONDAY_10AM))["started"] == []


@pytest.mark.asyncio
async def test_a_second_worker_never_starts_a_duplicate(world, monkeypatch):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    monkeypatch.setattr(autorun, "_TOKEN", "worker-b")
    monkeypatch.setattr(autorun, "_LOCAL", {})
    assert (await _tick(world, MONDAY_10AM))["started"] == []
    assert len(world.launched) == 1


@pytest.mark.asyncio
async def test_after_a_deploy_another_worker_takes_over(world, monkeypatch):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    # worker-a died: its task is gone, its row was swept as orphaned, and its
    # key expired.
    trading._RUNS.pop("run-1").cancel()
    await RunStore(world.db).close_orphaned()
    world.redis.data.clear()
    monkeypatch.setattr(autorun, "_TOKEN", "worker-b")
    monkeypatch.setattr(autorun, "_LOCAL", {})

    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice"]
    assert len(world.launched) == 2


@pytest.mark.asyncio
async def test_a_run_the_user_stopped_stays_stopped_today(world):
    await world.enable()
    await _tick(world, MONDAY_10AM)

    trading._RUNS.pop("run-1").cancel()
    await RunStore(world.db).mark_stopped("run-1")

    assert (await _tick(world, MONDAY_10AM))["started"] == []
    assert len(world.launched) == 1


@pytest.mark.asyncio
async def test_a_crashing_run_is_retried_up_to_the_daily_cap(world):
    await world.enable()
    for attempt in range(autorun.MAX_STARTS_PER_DAY + 2):
        await _tick(world, MONDAY_10AM)
        run_id = f"run-{len(world.launched)}"
        if run_id in trading._RUNS:
            trading._RUNS.pop(run_id).cancel()
            await RunStore(world.db).mark_error(run_id, "boom")
    assert len(world.launched) == autorun.MAX_STARTS_PER_DAY


@pytest.mark.asyncio
async def test_a_manual_intraday_run_is_not_doubled(world):
    await world.enable()
    runs = RunStore(world.db)
    await runs.create(run_id="manual", user_id="alice", mode="INTRADAY", universe=[], params={"origin": "manual"})
    await runs.collection.update_one({"run_id": "manual"}, {"$set": {"started_at": MONDAY_10AM}})

    assert (await _tick(world, MONDAY_10AM))["started"] == []


@pytest.mark.asyncio
async def test_the_run_stops_at_the_close_and_when_turned_off(world, monkeypatch):
    stopped = []

    async def stop(run_id):
        stopped.append(run_id)
        return True
    monkeypatch.setattr(trading, "stop_background_run", stop)

    await world.enable()
    await _tick(world, MONDAY_10AM)
    assert (await _tick(world, MONDAY_EVENING))["stopped"] == ["alice"]
    assert stopped == ["run-1"]
    assert "autorun:alice" not in world.redis.data

    # Turned off mid-session: stopped on the next tick.
    await _tick(world, datetime(2026, 9, 29, 10, 0, tzinfo=IST))
    await world.db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"auto_paper_intraday": False}})
    assert (await _tick(world, datetime(2026, 9, 29, 10, 1, tzinfo=IST)))["stopped"] == ["alice"]


@pytest.fixture
def longterm(world, monkeypatch):
    """The long-term switch on, with exits, scan and Telegram recorded."""
    import backend.suggestions.exits as exits
    import backend.suggestions.notify as notify
    import backend.suggestions.scan as scan

    calls = {"exits": [], "scans": [], "sent": []}

    async def check_exits(db, user_id, now=None):
        calls["exits"].append(now)
        return [{"symbol": "SJVN", "reason": "target", "price": 60.0, "quantity": 10.0,
                 "entry_price": 55.0, "gross_pnl": 50.0}]

    async def scan_universe(db, user_id, **kwargs):
        calls["scans"].append(kwargs["source"])
        return []

    async def send(db, user_id, text):
        calls["sent"].append(text)
        return True

    async def not_due(db, user_id, now):
        return False  # the factor rebalance downloads market data; tested on its own

    from backend.factor import paper
    monkeypatch.setattr(exits, "check_exits", check_exits)
    monkeypatch.setattr(scan, "scan_universe", scan_universe)
    monkeypatch.setattr(notify, "notify", send)
    monkeypatch.setattr(paper, "due", not_due)
    return calls


@pytest.mark.asyncio
async def test_the_long_term_switch_never_starts_a_live_run(world, longterm):
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    result = await _tick(world, MONDAY_10AM)
    assert world.launched == []
    assert result["longterm"] == ["alice"]
    assert (await _tick(world, SUNDAY_10AM)).get("longterm") is None


@pytest.mark.asyncio
async def test_exits_are_checked_once_per_quarter_hour_and_reported(world, longterm):
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-25"  # Friday's 16:00 pass ran

    await _tick(world, datetime(2026, 9, 28, 10, 0, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 10, 7, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 10, 16, tzinfo=IST))

    assert len(longterm["exits"]) == 2
    assert sum("SJVN" in text for text in longterm["sent"]) == 2
    assert longterm["scans"] == []  # 16:00 was not missed


@pytest.mark.asyncio
async def test_a_missed_close_scan_is_caught_up_at_the_open(world, longterm):
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-24"  # Friday's pass never happened

    await _tick(world, datetime(2026, 9, 28, 9, 16, tzinfo=IST))
    assert longterm["scans"] == []  # before 09:20
    await _tick(world, datetime(2026, 9, 28, 9, 21, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 11, 0, tzinfo=IST))
    assert longterm["scans"] == ["scheduler"]  # once a day


@pytest.mark.asyncio
async def test_the_morning_pass_rebalances_the_factor_book_and_leaves_proposals_pending(world, longterm, monkeypatch):
    from backend.factor import paper
    from backend.suggestions.store import SuggestionStore

    calls = []

    async def rebalance(db, user_id, now=None):
        calls.append(user_id)
        return {"exposure": 0.0, "bought": [], "sold": [], "equity": 300000.0}

    async def due(db, user_id, now):
        return not calls

    monkeypatch.setattr(paper, "rebalance", rebalance)
    monkeypatch.setattr(paper, "due", due)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-25"
    store = SuggestionStore(world.db)
    now = datetime(2026, 9, 28, 9, 21, tzinfo=IST)
    await store.collection.insert_one({
        "id": "SJVN", "user_id": "alice", "mode": "LONGTERM", "symbol": "SJVN", "side": "BUY",
        "quantity": 10, "entry_ref": 55.0, "stop": 50.0, "target": 65.0, "option_contract": None,
        "strategy": "test", "status": "PENDING", "created_at": now, "expires_at": datetime(2026, 10, 9, tzinfo=IST),
    })

    await _tick(world, now)
    await _tick(world, datetime(2026, 9, 29, 9, 21, tzinfo=IST))  # next morning: not due again

    assert calls == ["alice"]
    assert (await store.list("alice", limit=10))[0]["status"] == "PENDING"  # no auto-buy
    assert any("risk-off" in text for text in longterm["sent"])
    assert any("waiting" in text for text in longterm["sent"])


@pytest.mark.asyncio
async def test_with_the_autopilot_on_engine_proposals_go_to_it(world, longterm, monkeypatch):
    from backend.autopilot import service
    from backend.suggestions.store import SuggestionStore

    submitted = []

    async def submit(db, redis, user_id, order, now=None, suggestion_id=None, quiet=False):
        submitted.append((order.symbol, order.source))
        assert quiet and suggestion_id == order.symbol  # one summary note; exits can find the proposal
        assert order.quantity == 10  # resized: min(10, per_trade_cap // entry 55) = 10
        return {"status": "FILLED", "price": 55.0} if order.symbol == "SJVN" else {"status": "REFUSED", "reason": "cap"}

    monkeypatch.setattr(service, "submit", submit)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True, "autopilot_enabled": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-25"
    store = SuggestionStore(world.db)
    now = datetime(2026, 9, 28, 9, 21, tzinfo=IST)
    for symbol in ("SJVN", "NHPC"):
        await store.collection.insert_one({
            "id": symbol, "user_id": "alice", "mode": "LONGTERM", "symbol": symbol, "side": "BUY",
            "quantity": 10, "entry_ref": 55.0, "stop": 50.0, "target": 65.0, "option_contract": None,
            "strategy": "test", "status": "PENDING", "created_at": now, "expires_at": datetime(2026, 10, 9, tzinfo=IST),
        })

    await _tick(world, now)

    assert sorted(submitted) == [("NHPC", "engine"), ("SJVN", "engine")]
    by = {s["symbol"]: s["status"] for s in await store.list("alice", limit=10)}
    assert by == {"SJVN": "EXECUTED", "NHPC": "PENDING"}  # refused ones wait for the user


@pytest.mark.asyncio
async def test_autopilot_login_reminder_once_before_the_open(world, longterm, monkeypatch):
    from backend.brokers import roles

    async def not_logged_in(user_id, role, credentials, redis=None, roles=None, get_adapter=None):
        raise roles_mod.RoleUnavailable("ai", "The AI account (Kite) is not logged in today.")

    roles_mod = roles
    monkeypatch.setattr(autorun, "adapter_for", not_logged_in)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "autopilot_enabled": True})
    await _tick(world, datetime(2026, 9, 28, 9, 2, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 9, 5, tzinfo=IST))
    reminders = [t for t in longterm["sent"] if "not logged in" in t]
    assert len(reminders) == 1 and "09:15" in reminders[0]


@pytest.mark.asyncio
async def test_deploy_restarts_do_not_use_up_the_daily_start_cap(world, monkeypatch):
    """On 2026-10-05 a day of deploys orphaned six auto runs; the crash-loop
    cap counted them as starts and refused a seventh, leaving open intraday
    positions with no run to square them off. A deploy is not a crash loop."""
    await world.enable()
    for worker in range(autorun.MAX_STARTS_PER_DAY + 1):
        await _tick(world, MONDAY_10AM)
        trading._RUNS.pop(f"run-{len(world.launched)}").cancel()
        await RunStore(world.db).close_orphaned()  # the deploy's restart sweep
        world.redis.data.clear()
        monkeypatch.setattr(autorun, "_TOKEN", f"worker-{worker}")
        monkeypatch.setattr(autorun, "_LOCAL", {})

    assert (await _tick(world, MONDAY_10AM))["started"] == ["alice"]


@pytest.mark.asyncio
async def test_a_run_whose_worker_died_is_swept_and_replaced_by_the_tick(world, monkeypatch):
    """The startup sweep ran while the dead worker's alive key was still
    fresh, so its run stayed RUNNING and blocked every new start (one run per
    mode). The tick sweeps again once that key has expired."""
    await world.enable()
    runs = RunStore(world.db)
    await runs.create(run_id="zombie", user_id="alice", mode="INTRADAY", universe=[], params={"origin": "auto"})
    await runs.collection.update_one({"run_id": "zombie"}, {"$set": {"boot_id": "dead-worker", "started_at": MONDAY_10AM}})

    await _tick(world, MONDAY_10AM)

    assert (await runs.get("zombie"))["status"] == "STOPPED"
    assert len(world.launched) == 1


# --- Phase 15.2: the pre-open game plan ---------------------------------------

MONDAY_0846 = datetime(2026, 9, 28, 8, 46, tzinfo=IST)


@pytest.fixture
def built(monkeypatch):
    from backend.plan import builder

    calls = []

    async def fake_build(db, redis, user_id, now, complete=None):
        calls.append(user_id)
        return {}
    monkeypatch.setattr(builder, "build_plan", fake_build)
    return calls


async def test_preopen_builds_one_plan_per_user_even_with_two_ticks(world, built):
    await world.enable("alice")
    await world.enable("bob")
    await _tick(world, MONDAY_0846)
    await _tick(world, MONDAY_0846)
    assert sorted(built) == ["alice", "bob"]


async def test_no_plan_outside_the_window(world, built):
    await world.enable()
    await _tick(world, datetime(2026, 9, 28, 8, 30, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 9, 20, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 27, 8, 50, tzinfo=IST))  # Sunday
    assert built == []


async def test_skip_day_plan_keeps_the_auto_run_from_starting(world):
    import json

    await world.enable()
    world.redis.data["plan:alice:2026-09-28"] = json.dumps({"skip_day": True})
    assert not await autorun._may_start(RunStore(world.db), "alice", "INTRADAY", MONDAY_10AM, redis=world.redis)
    assert await autorun._may_start(RunStore(world.db), "alice", "LONGTERM", MONDAY_10AM, redis=world.redis)
    assert (await _tick(world, MONDAY_10AM))["started"] == []
