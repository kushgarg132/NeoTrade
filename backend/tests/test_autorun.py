"""The daily intraday paper run starts itself at the open, exactly once
across workers, comes back after a deploy, respects a manual stop, and
stops at the close."""

import asyncio
from datetime import datetime, timedelta, timezone

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
    live = {"ready": True}  # a streaming broker session is logged in

    async def live_feed_ready(user_id):
        return live["ready"]

    monkeypatch.setattr(autorun, "live_feed_ready", live_feed_ready)
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
    yield type("W", (), {"db": db, "redis": redis, "launch": launch, "launched": launched, "enable": enable, "live": live})
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

    calls = {"exits": [], "scans": [], "sent": [], "passes": []}

    async def check_exits(db, user_id, now=None):
        calls["exits"].append(now)
        return [{"symbol": "SJVN", "reason": "target", "price": 60.0, "quantity": 10.0,
                 "entry_price": 55.0, "gross_pnl": 50.0}]

    async def scan_universe(db, user_id, **kwargs):
        calls["scans"].append(kwargs["source"])
        return []

    async def send(db, user_id, text, html=False):
        calls["sent"].append(text)
        return True

    async def not_due(db, user_id, now):
        return False  # the factor rebalance downloads market data; tested on its own

    async def daily_pass(db, redis=None, now=None):
        calls["passes"].append(now)
        return {}

    from backend import scheduler
    from backend.factor import paper
    monkeypatch.setattr(scheduler, "run_daily_jobs", daily_pass)
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
async def test_the_autopilot_keeps_the_long_term_pass_running(world, longterm):
    """The autopilot buys at the 09:20 pass and exits in it: with the
    long-term switch off it used to do nothing at all."""
    await world.db["user_prefs"].insert_one({"user_id": "alice", "autopilot_enabled": True})
    assert (await _tick(world, MONDAY_10AM))["longterm"] == ["alice"]


@pytest.mark.asyncio
async def test_the_autopilot_keeps_the_scan_on():
    from backend.prefs import PrefsStore

    db = AsyncMongoMockClient()["t"]
    await db["users"].insert_many([{"id": "alice"}, {"id": "bob"}])
    await db["user_prefs"].insert_many([
        {"user_id": "alice", "scan_enabled": False, "autopilot_enabled": True},
        {"user_id": "bob", "scan_enabled": False},
    ])
    assert [p["user_id"] for p in await PrefsStore(db).scan_enabled_users()] == ["alice"]


@pytest.mark.asyncio
async def test_exits_are_checked_once_per_quarter_hour_and_reported(world, longterm):
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-25"  # Friday's 16:00 pass ran

    await _tick(world, datetime(2026, 9, 28, 10, 0, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 10, 7, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 10, 16, tzinfo=IST))

    assert len(longterm["exits"]) == 2
    assert sum("SJVN" in text for text in longterm["sent"]) == 2
    assert longterm["passes"] == []  # 16:00 was not missed


@pytest.mark.asyncio
async def test_a_missed_close_scan_is_caught_up_at_the_open(world, longterm):
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-24"  # Friday's pass never happened

    await _tick(world, datetime(2026, 9, 28, 9, 16, tzinfo=IST))
    assert longterm["passes"] == []  # before 09:20
    await _tick(world, datetime(2026, 9, 28, 9, 21, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 11, 0, tzinfo=IST))
    await asyncio.sleep(0.05)  # the catch-up runs as a background task, off the tick
    # The whole missed pass, once, recorded as Friday's so Monday's 16:00 still runs.
    assert len(longterm["passes"]) == 1
    assert world.redis.data["scheduler:last_pass"] == "2026-09-25"


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
    assert any("for your account" in text for text in longterm["sent"])


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
    by = {s["symbol"]: (s["status"], s.get("ai_order")) for s in await store.list("alice", limit=10)}
    # The AI took SJVN; the idea stays pending, the user's to take on their own account.
    assert by == {"SJVN": ("PENDING", "FILLED"), "NHPC": ("PENDING", None)}


@pytest.mark.asyncio
@pytest.mark.real_gate
async def test_live_autopilot_takes_only_proposals_from_proven_strategies(world, longterm, monkeypatch):
    """Live, a proposal goes to the autopilot only if its strategy passed
    both gates; the rest wait for the user. 2026-10-07: paper autopilot
    bought TRENT on macd_crossover, whose backtest fails (PF 0.87)."""
    from backend.autopilot import service
    from backend.suggestions.store import SuggestionStore

    submitted = []

    async def submit(db, redis, user_id, order, now=None, suggestion_id=None, quiet=False):
        submitted.append(order.symbol)
        return {"status": "SENT"}

    async def proven(db, user_id, names, account_size):
        assert names == {"good", "bad"}
        return {"good"}

    monkeypatch.setattr(service, "submit", submit)
    monkeypatch.setattr("backend.risk.paper_gate.proven_strategies", proven)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True,
                                             "autopilot_enabled": True, "autopilot_live": True})
    world.redis.data["scheduler:last_pass"] = "2026-09-25"
    store = SuggestionStore(world.db)
    now = datetime(2026, 9, 28, 9, 21, tzinfo=IST)
    for symbol, strategy in (("SJVN", "good"), ("NHPC", "bad")):
        await store.collection.insert_one({
            "id": symbol, "user_id": "alice", "mode": "LONGTERM", "symbol": symbol, "side": "BUY",
            "quantity": 10, "entry_ref": 55.0, "stop": 50.0, "target": 65.0, "option_contract": None,
            "strategy": strategy, "status": "PENDING", "created_at": now, "expires_at": datetime(2026, 10, 9, tzinfo=IST),
        })

    await _tick(world, now)

    assert submitted == ["SJVN"]
    by = {s["symbol"]: (s["status"], s.get("ai_order")) for s in await store.list("alice", limit=10)}
    assert by == {"SJVN": ("PENDING", "SENT"), "NHPC": ("PENDING", None)}


@pytest.mark.asyncio
@pytest.mark.real_gate
async def test_proven_strategies_need_both_gates():
    from backend.risk.paper_gate import proven_strategies

    db = AsyncMongoMockClient()["t"]
    assert await proven_strategies(db, "alice", {"macd_crossover"}, 25_000.0) == set()  # never backtested
    await db["strategy_backtests"].insert_one({"strategy_name": "macd_crossover", "run_at": datetime.now(timezone.utc),
                                               "passed": True, "result": {}})
    assert await proven_strategies(db, "alice", {"macd_crossover"}, 25_000.0) == set()  # no paper record


@pytest.mark.asyncio
async def test_login_reminder_lists_only_logged_out_brokers_twice_a_morning(world, longterm, monkeypatch):
    from types import SimpleNamespace

    states = {"kite": "EXPIRED", "upstox": "ACTIVE"}

    async def adapter(broker, user_id, credentials, redis):
        async def state():
            return SimpleNamespace(value=states[broker])

        async def login_url():
            return f"https://{broker}.example/login?a=1&b=2"
        return SimpleNamespace(state=state, login_url=login_url)

    monkeypatch.setattr("backend.brokers.registry.get_broker_adapter", adapter)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"kite": "ai", "upstox": "mine"}})
    for minute in (25, 31, 40):  # 08:25 too early, 08:31 sends, 08:40 already sent
        await _tick(world, datetime(2026, 9, 28, 8, minute, tzinfo=IST))
    await _tick(world, datetime(2026, 9, 28, 9, 6, tzinfo=IST))  # still logged out: one more

    reminders = [t for t in longterm["sent"] if "Log in before 9:15" in t]
    assert len(reminders) == 2
    assert 'href="https://kite.example/login?a=1&amp;b=2"' in reminders[0] and "upstox" not in reminders[0].lower()


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
    await _tick(world, datetime(2026, 9, 28, 15, 40, tzinfo=IST))  # after the close
    await _tick(world, datetime(2026, 9, 27, 8, 50, tzinfo=IST))  # Sunday
    assert built == []


async def test_no_plan_until_a_live_feed_then_one_before_the_run_starts(world, built):
    await world.enable()
    world.live["ready"] = False
    await _tick(world, MONDAY_0846)
    assert built == []  # no live feed, no auto run today: a plan would be an unused LLM call
    world.live["ready"] = True
    done = await _tick(world, MONDAY_10AM)  # logged in late: planned in the same tick, before the start
    assert built == ["alice"] and done["started"] == ["alice"]


async def test_skip_day_plan_keeps_the_auto_run_from_starting(world):
    import json

    await world.enable()
    world.redis.data["plan:alice:2026-09-28"] = json.dumps({"skip_day": True})
    assert not await autorun._may_start(RunStore(world.db), "alice", "INTRADAY", MONDAY_10AM, redis=world.redis)
    assert await autorun._may_start(RunStore(world.db), "alice", "LONGTERM", MONDAY_10AM, redis=world.redis)
    assert (await _tick(world, MONDAY_10AM))["started"] == []


@pytest.mark.asyncio
async def test_the_auto_intraday_run_waits_for_a_live_broker_feed(world):
    """Paper results from 15-minute-old candles say nothing about a live
    strategy: with no streaming broker logged in, the run does not start;
    it starts on the first tick after the login."""
    await world.enable()
    world.live["ready"] = False
    assert (await _tick(world, MONDAY_10AM))["started"] == []
    world.live["ready"] = True
    assert (await _tick(world, MONDAY_10AM + timedelta(minutes=1)))["started"] == ["alice"]
