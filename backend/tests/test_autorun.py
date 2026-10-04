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

    yield type("W", (), {"db": db, "redis": _Redis(), "launch": launch, "launched": launched, "enable": enable})
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

    monkeypatch.setattr(exits, "check_exits", check_exits)
    monkeypatch.setattr(scan, "scan_universe", scan_universe)
    monkeypatch.setattr(notify, "notify", send)
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
async def test_pending_long_term_stock_proposals_are_bought_on_paper_at_the_open(world, longterm, monkeypatch):
    import backend.marks as marks
    from backend.suggestions.store import SuggestionStore

    async def mark_prices(db, symbols):
        return {"SJVN": 55.0}  # no mark for NHPC

    monkeypatch.setattr(marks, "mark_prices", mark_prices)
    await world.db["user_prefs"].insert_one({"user_id": "alice", "auto_paper_longterm": True})
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
    await _tick(world, datetime(2026, 9, 28, 9, 40, tzinfo=IST))

    by_symbol = {s["symbol"]: s for s in await store.list("alice", limit=10)}
    assert by_symbol["SJVN"]["status"] == "EXECUTED"
    assert by_symbol["NHPC"]["status"] == "PENDING"  # no mark: left for the user
    trades = await world.db["paper_trades"].find({"user_id": "alice", "symbol": "SJVN"}).to_list(None)
    assert len(trades) == 1 and trades[0]["status"] == "OPEN"
    assert any("bought 1" in text for text in longterm["sent"])
