import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.builder import draft, store
from backend.components.shared.models import BacktestResult
from backend.strategies.built import set_active

NOW = datetime(2026, 10, 9, 10, 30, tzinfo=timezone.utc)  # Friday 16:00 IST
START, END = NOW - timedelta(days=365), NOW

GAP = {"setup": {"gap": {"direction": "down", "min_pct": 1.0}}, "side": "long",
       "filters": {"time_window": {"start": "09:30", "end": "14:45"}},
       "stop": {"atr_multiple": 1.0}, "target": {"r_multiple": 2.0}}
ORB = {"setup": {"orb_break": {"range_minutes": 15}}, "side": "short",
       "stop": {"setup_bar": True}, "target": {"r_multiple": 1.5}}


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, px=None, nx=False, **_):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)

    async def hset(self, key, mapping):
        self.data.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})


def trades(after_holdout=1000.0, before_holdout=1000.0):
    """One trade per weekday over the year; every third day loses half a win."""
    out = []
    cut = END - timedelta(days=90)
    for i, day in enumerate(pd.bdate_range(START.date(), END.date() - timedelta(days=1))):
        at = datetime.combine(day.date(), datetime.min.time(), timezone.utc) + timedelta(hours=5)
        base = after_holdout if at >= cut else before_holdout
        out.append({"timestamp": at.isoformat(), "net_pnl": base if i % 3 else -abs(base) / 2})
    return out


def result(pf=1.5, n=300, dd=0.08, days=365, trade_list=None):
    trade_list = trades() if trade_list is None else trade_list
    return BacktestResult(symbol="X", start_date=END - timedelta(days=days), end_date=END, total_trades=n,
                          win_rate=0.6, profit_factor=pf, total_pnl=sum(t["net_pnl"] for t in trade_list),
                          max_drawdown=dd, sharpe_ratio=1.0, trades=trade_list)


def llm_of(*specs, calls=None):
    async def llm(system, prompt):
        if calls is not None:
            calls.append(prompt)
        return json.dumps({"strategies": [{"spec": s, "thesis": "because"} for s in specs]})
    return llm


def backtest_of(res, calls=None):
    async def backtest(strategy, start, end, account=None):
        if calls is not None:
            calls.append(strategy.spec.name)
        return res
    return backtest


@pytest.fixture
def env(monkeypatch):
    set_active([])
    sent = []

    async def notify(db, user_id, text):
        sent.append((user_id, text))
        return True

    async def nifty():
        return []

    monkeypatch.setattr(draft, "notify", notify)
    monkeypatch.setattr("backend.portfolio.service._nifty", nifty)
    db = AsyncMongoMockClient()["t"]
    yield db, FakeRedis(), sent
    set_active([])


async def _admin(db):
    await db["users"].insert_one({"id": "admin", "role": "admin"})


async def _drafts(db):
    return {d["slug"]: d for d in await store.all_drafts(db)}


async def test_pass_becomes_active_and_records_the_gate_row(env):
    db, redis, sent = env
    await _admin(db)
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result()))
    slug = out["passed"][0]
    doc = (await _drafts(db))[slug]
    assert doc["status"] == "active" and out["drafted"] == 1 and out["rejected"] == []
    assert doc["metrics"]["year"]["trades"] == 300 and doc["metrics"]["holdout"]["net"] > 0
    assert doc["sharpe"] > 0 and doc["trials"] == 1 and doc["thesis"] == "because" and doc["description"]
    gate = await db["strategy_backtests"].find_one({"strategy_name": f"built:{slug}"})
    assert gate["passed"] is True
    assert sent == [("admin", sent[0][1])]
    assert sent[0][1].startswith(f"🧪 Strategy builder: 1 drafted, 1 passed: built:{slug} (PF 1.50, 300 trades, "
                                 "last 90 days +₹")
    assert redis.data["job:last:strategy_builder"]["ok"] == "1"
    assert "builder:lock" not in redis.data


async def test_gate_fail_is_rejected_with_reason(env):
    db, redis, _ = env
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result(pf=1.12)))
    (slug, reason), = out["rejected"]
    assert reason == "gate: PF 1.12 < 1.3"
    doc = (await _drafts(db))[slug]
    assert doc["status"] == "rejected" and doc["verdict"] == reason and doc["sharpe"] is not None
    assert (await db["strategy_backtests"].find_one({"strategy_name": f"built:{slug}"}))["passed"] is False
    out = await draft.run(db, redis, NOW, llm=llm_of(ORB), backtest=backtest_of(result(n=18, dd=0.22, days=300)))
    assert out["rejected"][0][1] == "gate: 300 days < 365"


async def test_holdout_fail_is_rejected(env):
    db, redis, _ = env
    res = result(trade_list=trades(after_holdout=-200.0, before_holdout=3000.0))
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(res))
    (_, reason), = out["rejected"]
    assert reason.startswith("holdout: −₹") and reason.endswith(" over the last 90 days")


async def test_deflated_sharpe_fail_is_rejected(env):
    db, redis, _ = env
    for i in range(20):
        await store.insert(db, {"slug": f"old-{i}", "spec": {}, "status": "rejected", "sharpe": 3.0 * (i % 2),
                                "drafted_at": NOW - timedelta(days=30)})
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result()))
    (slug, reason), = out["rejected"]
    assert reason.startswith("deflated Sharpe ") and reason.endswith(" < 0.95 over 21 drafts")
    assert (await _drafts(db))[slug]["trials"] == 21


async def test_invalid_and_duplicate_drafts_are_rejected_not_tested(env):
    db, redis, _ = env
    tested = []
    bad = {k: v for k, v in GAP.items() if k != "side"}
    out = await draft.run(db, redis, NOW, llm=llm_of(bad, GAP, dict(GAP), ORB),
                          backtest=backtest_of(result(), tested))
    assert out["drafted"] == 3  # at most three per run; ORB is never read
    first = out["passed"][0]
    assert tested == [f"built:{first}"]
    assert sorted(r for _, r in out["rejected"]) == sorted(["side must be long or short", f"duplicate of {first}"])
    docs = await _drafts(db)
    assert [d["status"] for d in docs.values()].count("rejected") == 2 and len(docs) == 3
    # The same spec next week is a duplicate of the stored one; its slug would collide anyway.
    out = await draft.run(db, redis, NOW + timedelta(days=7), llm=llm_of(ORB, GAP), backtest=backtest_of(result()))
    assert (out["rejected"][-1][1]) == f"duplicate of {first}"
    assert len(set(await db[store.COLLECTION].distinct("slug"))) == 5


async def test_slug_collision_gets_a_suffix(env):
    db, redis, _ = env
    await store.insert(db, {"slug": "gap-down-time-window-long", "spec": {}, "status": "rejected", "drafted_at": NOW})
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result()))
    assert out["passed"] == ["gap-down-time-window-long-2"]


async def test_sixth_pass_retires_the_weakest_active(env):
    db, redis, _ = env
    for i in range(5):
        await store.insert(db, {"slug": f"a{i}", "spec": ORB, "status": "active",
                                "drafted_at": NOW - timedelta(days=10 - i)})
        for user, pnl in (("u1", 100.0 * i), ("u2", 50.0)):
            await db["paper_trades"].insert_one({"user_id": user, "venue": "paper", "status": "CLOSED",
                                                 "strategy": f"built:a{i}", "realized_pnl": pnl, "costs": 10.0})
    # Paper net across users: a0 30, a1 130, ... a4 430 -- a0 is the weakest.
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result()))
    docs = await _drafts(db)
    assert out["retired"] == ["a0"] and docs["a0"]["status"] == "retired"
    assert sum(d["status"] == "active" for d in docs.values()) == 5


async def test_paused_30_days_is_retired(env):
    db, redis, _ = env
    await _admin(db)
    for slug in ("old", "young"):
        await store.insert(db, {"slug": slug, "spec": ORB, "status": "active", "drafted_at": NOW})
    await db["learning_state"].insert_one({"user_id": "admin", "paused": {
        "built:old": NOW - timedelta(days=31), "built:young": NOW - timedelta(days=5), "orb": NOW - timedelta(days=90)}})
    out = await draft.run(db, redis, NOW, llm=llm_of(), backtest=backtest_of(result()))
    docs = await _drafts(db)
    assert out["retired"] == ["old"]
    assert docs["old"]["status"] == "retired" and docs["young"]["status"] == "active"


async def test_no_history_source_leaves_drafts_testing(env, monkeypatch):
    db, redis, _ = env

    async def none(db, redis):
        return None, None

    monkeypatch.setattr("backend.risk.gate_backtest.intraday_history", none)
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP))
    assert out["drafted"] == 1 and out["passed"] == [] and out["rejected"] == []
    assert [d["status"] for d in (await _drafts(db)).values()] == ["testing"]
    # Next week still no history: nothing new is drafted while drafts wait.
    calls = []
    out = await draft.run(db, redis, NOW + timedelta(days=7), llm=llm_of(ORB, calls=calls))
    assert calls == [] and out["drafted"] == 0
    # History back: the waiting draft is tested before anything new.
    tested = []
    out = await draft.run(db, redis, NOW + timedelta(days=14), llm=llm_of(ORB),
                          backtest=backtest_of(result(), tested))
    assert len(tested) == 2 and tested[0].startswith("built:gap-") and len(out["passed"]) == 2


async def test_second_run_exits_on_the_lock(env):
    db, redis, _ = env
    calls = []
    await redis.set("builder:lock", "1")
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP, calls=calls), backtest=backtest_of(result()))
    assert out == {"skipped": "running"} and calls == []
    assert redis.data["builder:lock"] == "1"  # the running job's lock is left alone


async def test_start_if_due_only_fridays_once_a_week(env, monkeypatch):
    db, _, _ = env
    spawned = []

    async def spawn():
        spawned.append(1)

    monkeypatch.setattr(draft, "spawn", spawn)
    assert await draft.start_if_due(db, NOW - timedelta(days=1)) is False  # Thursday
    assert await draft.start_if_due(db, NOW) is True
    assert await draft.start_if_due(db, NOW + timedelta(hours=8)) is False  # Friday night, same week
    assert await draft.start_if_due(db, NOW + timedelta(days=7)) is True
    assert len(spawned) == 2
    assert await db["builder_runs"].find_one({"week": "2026-W41"})


async def test_llm_garbage_drafts_nothing(env):
    db, redis, sent = env
    await _admin(db)

    async def llm(system, prompt):
        assert "regime_is" in prompt and "risk_on" in prompt and "{{" not in prompt
        return "Sorry, I can't help with that"

    out = await draft.run(db, redis, NOW, llm=llm, backtest=backtest_of(result()))
    assert out == {"drafted": 0, "passed": [], "rejected": [], "retired": []}
    assert await store.all_drafts(db) == []
    assert redis.data["job:last:strategy_builder"]["ok"] == "1"
    assert sent and "0 drafted" in sent[0][1]


async def test_backtest_asks_for_more_than_a_year(env):
    """2026-10-07: a request of exactly 365 days came back as 363 days of bars
    and failed the gate's 365-day minimum."""
    db, redis, _ = env
    await _admin(db)
    windows = []

    async def backtest(strategy, start, end, account=None):
        windows.append(end - start)
        return result()

    await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest)
    assert windows == [timedelta(days=372)]


async def test_a_cut_off_reply_is_retried_once_with_a_new_prompt(env):
    """2026-10-07: the first live run got a truncated JSON reply, and the
    gateway's response cache replays it for the same prompt."""
    db, redis, _ = env
    await _admin(db)
    prompts = []
    good = llm_of(GAP)

    async def llm(system, prompt):
        prompts.append(prompt)
        return '```json\n{"strategies": [{"spec": {"setup"' if len(prompts) == 1 else await good(system, prompt)

    out = await draft.run(db, redis, NOW, llm=llm, backtest=backtest_of(result()))
    assert out["drafted"] == 1 and len(prompts) == 2 and prompts[1] != prompts[0]


async def test_backtest_failure_rejects_that_draft_and_tests_the_next(env):
    db, redis, _ = env
    tested = []

    async def backtest(strategy, start, end, account=None):
        tested.append(strategy.spec.name)
        if len(tested) == 1:
            raise TimeoutError("history gap")
        return result()

    out = await draft.run(db, redis, NOW, llm=llm_of(GAP, ORB), backtest=backtest)
    statuses = {d["slug"]: d["status"] for d in (await _drafts(db)).values()}
    first = tested[0].removeprefix("built:")
    assert len(tested) == 2 and statuses[first] == "rejected" and out["drafted"] == 2
    assert (await _drafts(db))[first]["verdict"] == "test failed: TimeoutError"  # re-testable, not stuck
    assert [s for s, st in statuses.items() if st == "active"] == out["passed"] != [first]
    assert redis.data["job:last:strategy_builder"]["ok"] == "1" and "builder:lock" not in redis.data


async def test_history_source_error_counts_as_no_source(env, monkeypatch):
    db, redis, _ = env

    async def boom(db, redis):
        raise ConnectionError("upstox down")

    monkeypatch.setattr("backend.risk.gate_backtest.intraday_history", boom)
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP))
    assert out["drafted"] == 1 and [d["status"] for d in (await _drafts(db)).values()] == ["testing"]


async def test_zero_account_size_tests_nothing(env, monkeypatch):
    db, redis, _ = env
    calls = []

    async def zero(db):
        return {"account_size": 0.0, "max_exposure": 0.0, "per_trade_cap": 0.0}

    monkeypatch.setattr("backend.risk.gate_backtest.backtest_account", zero)
    await store.insert(db, {"slug": "waiting", "spec": GAP, "status": "testing", "drafted_at": NOW})
    out = await draft.run(db, redis, NOW, llm=llm_of(ORB, calls=calls), backtest=backtest_of(result()))
    assert out["drafted"] == 0 and calls == [] and (await _drafts(db))["waiting"]["status"] == "testing"
    assert redis.data["job:last:strategy_builder"] == {**redis.data["job:last:strategy_builder"], "ok": "0",
                                                       "note": "account size is 0"}
    assert "builder:lock" not in redis.data


async def test_non_finite_sharpe_is_rejected_and_not_stored(env):
    db, redis, _ = env
    res = result(trade_list=[{**t, "net_pnl": float("nan")} for t in trades()])
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(res))
    (slug, reason), = out["rejected"]
    assert reason == "non-finite Sharpe" and (await _drafts(db))[slug]["sharpe"] is None
    assert await store.trial_sharpes(db) == []


async def test_start_if_due_claims_the_week_atomically(env, monkeypatch):
    import asyncio

    db, _, _ = env
    spawned = []

    async def spawn():
        spawned.append(1)

    monkeypatch.setattr(draft, "spawn", spawn)
    assert sorted(await asyncio.gather(*(draft.start_if_due(db, NOW) for _ in range(5)))) == [False] * 4 + [True]
    assert len(spawned) == 1 and await db["builder_runs"].count_documents({}) == 1


async def test_paper_net_counts_every_non_live_venue(env):
    db, _, _ = env
    for venue, pnl in (("paper", 100.0), ("shadow", 50.0), ("live", 1000.0)):
        await db["paper_trades"].insert_one({"strategy": "built:x", "venue": venue, "status": "CLOSED",
                                             "realized_pnl": pnl, "costs": 0.0})
    assert await draft._paper_net(db, "x") == 150.0


async def test_start_if_due_duplicate_key_means_already_claimed(env, monkeypatch):
    from pymongo.errors import DuplicateKeyError

    db, _, _ = env
    spawned = []

    async def spawn():
        spawned.append(1)

    class Runs:
        async def update_one(self, *_, **__):
            raise DuplicateKeyError("E11000 duplicate key")

    class Db:
        def __getitem__(self, name):
            assert name == "builder_runs"
            return Runs()

    monkeypatch.setattr(draft, "spawn", spawn)
    assert await draft.start_if_due(Db(), NOW) is False and spawned == []


def sized_backtest(res, seen):
    async def backtest(strategy, start, end, account=None):
        seen.append((strategy.spec.name, account))
        return res
    return backtest


async def _user_draft(db, slug="mine", owner="u1", status="testing"):
    await store.insert(db, {"slug": slug, "spec": GAP, "status": status, "drafted_at": NOW, "owner_id": owner})


async def test_test_one_tests_only_that_draft_without_llm(env):
    db, redis, _ = env
    await _user_draft(db)
    await _user_draft(db, "other")
    seen = []
    out = await draft.test_one(db, redis, "mine", NOW, backtest=sized_backtest(result(), seen))
    assert [n for n, _ in seen] == ["built:mine"]
    assert out["slug"] == "mine" and out["status"] == "active"
    docs = await _drafts(db)
    assert docs["mine"]["status"] == "active" and docs["other"]["status"] == "testing"
    assert "builder:test:mine" not in redis.data


async def test_test_one_runs_while_the_weekly_lock_is_held(env):
    db, redis, _ = env
    redis.data["builder:lock"] = "x"
    await _user_draft(db)
    out = await draft.test_one(db, redis, "mine", NOW, backtest=sized_backtest(result(), []))
    assert out["status"] == "active" and redis.data["builder:lock"] == "x"


async def test_test_one_uses_owner_sizing_and_trials(env):
    db, redis, _ = env
    await db["user_prefs"].insert_one({"user_id": "u1", "account_size": 50_000.0, "max_exposure": 40_000.0,
                                       "per_trade_cap": 5_000.0})
    await _user_draft(db)
    await _user_draft(db, "u1-old", status="rejected")
    await _user_draft(db, "u2-old", owner="u2", status="rejected")
    await _user_draft(db, "ai-old", owner=None, status="rejected")
    for slug, sharpe in (("u1-old", 1.0), ("u2-old", 2.0), ("ai-old", 3.0)):
        await db[store.COLLECTION].update_one({"slug": slug}, {"$set": {"sharpe": sharpe}})
    seen = []
    await draft.test_one(db, redis, "mine", NOW, backtest=sized_backtest(result(), seen))
    assert seen[0][1] == {"account_size": 50_000.0, "max_exposure": 40_000.0, "per_trade_cap": 5_000.0}
    assert (await _drafts(db))["mine"]["trials"] == 2  # u1's one earlier draft + this one


async def test_owner_without_prefs_uses_defaults(env):
    db, redis, _ = env
    await _user_draft(db)
    seen = []
    await draft.test_one(db, redis, "mine", NOW, backtest=sized_backtest(result(), seen))
    assert seen[0][1]["account_size"] == 1_000_000.0


async def test_test_one_no_history_waits(env, monkeypatch):
    db, redis, _ = env

    async def none(db, redis):
        return None, None

    monkeypatch.setattr("backend.risk.gate_backtest.intraday_history", none)
    await _user_draft(db)
    out = await draft.test_one(db, redis, "mine", NOW)
    assert out["status"] == "testing" and out["verdict"] == "waiting for market history"
    assert (await _drafts(db))["mine"]["verdict"] == "waiting for market history"


async def test_test_one_failure_is_rejected_and_other_states_are_skipped(env):
    db, redis, _ = env
    await _user_draft(db)
    await _user_draft(db, "done", status="active")

    async def boom(strategy, start, end, account=None):
        raise TimeoutError("gap")

    out = await draft.test_one(db, redis, "mine", NOW, backtest=boom)
    assert out["status"] == "rejected" and out["verdict"] == "test failed: TimeoutError"
    assert (await _drafts(db))["mine"]["status"] == "rejected"
    assert (await draft.test_one(db, redis, "done", NOW, backtest=boom))["status"] == "active"


async def test_weekly_run_retests_a_users_waiting_draft_with_owner_sizing(env):
    db, redis, _ = env
    await _admin(db)
    await db["user_prefs"].insert_one({"user_id": "u1", "account_size": 50_000.0, "max_exposure": 40_000.0,
                                       "per_trade_cap": 5_000.0})
    await _user_draft(db)
    seen = []
    out = await draft.run(db, redis, NOW, llm=llm_of(), backtest=sized_backtest(result(), seen))
    assert out["passed"] == ["mine"] and seen[0][1]["account_size"] == 50_000.0


async def test_retest_counts_as_a_new_trial(env):
    db, redis, _ = env
    await _user_draft(db)
    await _user_draft(db, "u1-legacy", status="rejected")  # tested before trial_history existed
    await db[store.COLLECTION].update_one({"slug": "u1-legacy"}, {"$set": {"sharpe": 1.0}})
    counts = []
    for _ in range(3):  # test, rejected, re-test, ...
        await draft.test_one(db, redis, "mine", NOW, backtest=backtest_of(result(pf=1.0)))
        doc = (await _drafts(db))["mine"]
        assert doc["status"] == "rejected"
        counts.append(doc["trials"])
        await store.set_status(db, "mine", "testing")
    assert counts == [2, 3, 4] and len(doc["trial_history"]) == 3
    assert len(await store.trial_sharpes(db, "u1")) == 4


async def test_ai_draft_is_never_a_duplicate_of_a_users(env):
    db, redis, _ = env
    await _user_draft(db, "alices-private-gap", status="active")
    out = await draft.run(db, redis, NOW, llm=llm_of(GAP), backtest=backtest_of(result()))
    assert out["drafted"] == 1 and not any("alices-private-gap" in v for _, v in out["rejected"])


# --- swing (docs/superpowers/specs/2026-10-07-swing-builder-design.md §3-4) ---

SWING = {"horizon": "swing", "setup": {"breakout_n": {"days": 20}}, "filters": {}, "side": "long",
         "stop": {"atr_multiple": 2.0}, "target": {"r_multiple": 3.0}, "max_hold_days": {"days": 10}}
SPAN = NOW - timedelta(days=3 * 365)  # what the checks see; the backtest starts 300 days earlier


def swing_trades(gain=3000.0, recent=None, warmup_loss=None):
    """A round trip every fifth weekday over the 3 years: two wins of `gain`, then a loss of half.
    `recent(at)` overrides the net of trips at `at`; `warmup_loss` adds one trip before the span."""
    out = []

    def trip(at, net, sym="AAA"):
        exit_at = at + timedelta(days=1)
        out.extend([{"symbol": sym, "side": "BUY", "quantity": 10, "timestamp": at.isoformat(), "net_pnl": -10.0, "realized_pnl": -10.0},
                    {"symbol": sym, "side": "SELL", "quantity": 10, "timestamp": exit_at.isoformat(),
                     "net_pnl": net + 10.0, "realized_pnl": net + 10.0}])

    if warmup_loss is not None:
        trip(SPAN - timedelta(days=30), -warmup_loss, "WARM")
    for i, day in enumerate(pd.bdate_range((SPAN + timedelta(days=1)).date(), (NOW - timedelta(days=3)).date())[::5]):
        at = datetime.combine(day.date(), datetime.min.time(), timezone.utc) + timedelta(hours=5)
        net = gain if i % 3 else -gain / 2
        trip(at, recent(at, net) if recent else net)
    return out


def swing_result(trade_list):
    return BacktestResult(symbol="X", start_date=NOW - timedelta(days=3 * 365 + 300), end_date=NOW, total_trades=1,
                          win_rate=0.5, profit_factor=9.0, total_pnl=0.0, max_drawdown=0.0, sharpe_ratio=0.0,
                          trades=trade_list)


def closes(growth, start=SPAN):
    days = pd.bdate_range(start.date(), NOW.date())
    return pd.DataFrame({"close": [100.0 * (1 + growth * i / (len(days) - 1)) for i in range(len(days))]},
                        index=pd.DatetimeIndex(days))


def swing_history(monkeypatch, res, growth=0.10, seen=None):
    """`draft._history` for swing: the given result on bars that grow `growth` over the span."""
    frames = {"AAA": closes(growth), "BBB": closes(growth),
              "LATE": closes(5.0, SPAN + timedelta(days=20))}  # no bar on the first day: not in the benchmark

    async def history(db, redis, horizon):
        if horizon != "swing":
            return None

        async def backtest(strategy, start, end, account):
            if seen is not None:
                seen.append((strategy.spec.name, strategy.spec.timeframe, start, end))
            return res
        return backtest, {"universe": ["AAA", "BBB"], "symbol_for_token": {}, "bars": frames}

    monkeypatch.setattr(draft, "_history", history)


async def _swing_draft(db, slug="swingy", owner="u1"):
    await store.insert(db, {"slug": slug, "spec": SWING, "status": "testing", "drafted_at": NOW, "owner_id": owner})


async def test_swing_draft_passes_all_four_checks(env, monkeypatch):
    db, redis, _ = env
    seen = []
    swing_history(monkeypatch, swing_result(swing_trades(warmup_loss=500_000.0)), seen=seen)
    await _swing_draft(db)
    await _user_draft(db, "u1-intraday", status="rejected")  # an intraday trial: not counted for swing
    await db[store.COLLECTION].update_one({"slug": "u1-intraday"}, {"$set": {"sharpe": 2.0}})
    out = await draft.test_one(db, redis, "swingy", NOW)
    doc = (await _drafts(db))["swingy"]
    assert out["status"] == "active", out["verdict"]
    assert seen == [("built:swingy", "1d", NOW - timedelta(days=3 * 365 + 300), NOW)]
    assert doc["trials"] == 1 and doc["sharpe"] > 0
    assert doc["metrics"]["year"]["trades"] == len(swing_trades()) // 2  # the warm-up trip is not counted
    bench = doc["metrics"]["benchmark"]
    assert bench["buy_hold_pct"] == pytest.approx(10.0 - 0.2854, abs=0.01)
    assert bench["strategy_pct"] == pytest.approx(sum(t["net_pnl"] for t in swing_trades()) / 1e4, abs=0.01)
    gate = await db["strategy_backtests"].find_one({"strategy_name": "built:swingy"})
    assert gate["passed"] is True


async def test_swing_rejected_on_benchmark_with_verdict(env, monkeypatch):
    db, redis, _ = env
    swing_history(monkeypatch, swing_result(swing_trades()), growth=0.50)
    await _swing_draft(db)
    out = await draft.test_one(db, redis, "swingy", NOW)
    strategy = sum(t["net_pnl"] for t in swing_trades()) / 1e4
    assert out["status"] == "rejected"
    assert out["verdict"] == f"benchmark: {strategy:+.1f}% < buy-and-hold +49.7%"


async def test_swing_holdout_is_180_days(env, monkeypatch):
    db, redis, _ = env

    def recent(at, net):  # losing 180..90 days ago, winning in the last 90: the intraday holdout would pass
        return -5000.0 if NOW - timedelta(days=180) <= at < NOW - timedelta(days=90) else net

    swing_history(monkeypatch, swing_result(swing_trades(gain=6000.0, recent=recent)))
    await _swing_draft(db)
    out = await draft.test_one(db, redis, "swingy", NOW)
    assert out["status"] == "rejected"
    assert out["verdict"].startswith("holdout: −₹") and out["verdict"].endswith(" over the last 180 days")


async def test_swing_waits_with_too_few_symbols(env):
    from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
    from backend.datalayer import bars

    db, redis, _ = env
    frame = closes(0.1, NOW - timedelta(days=30)).assign(open=100.0, high=101.0, low=99.0, volume=1000.0)
    frame.index = pd.bdate_range(end=bars.today_ist(), periods=len(frame))
    for symbol in ALL_SCAN_STOCKS[:29]:
        await bars.write(db, symbol, frame)
    assert await draft._history(db, redis, "swing") is None
    await _swing_draft(db)
    out = await draft.test_one(db, redis, "swingy", NOW)
    assert out == {"slug": "swingy", "status": "testing", "verdict": "waiting for market history"}


async def test_weekly_run_drafts_both_horizons(env, monkeypatch):
    db, redis, _ = env
    await _admin(db)
    swing_history(monkeypatch, swing_result(swing_trades()))
    prompts = {}
    swing_reply = {k: v for k, v in SWING.items() if k != "horizon"}  # the run sets it from the call

    async def llm(system, prompt):
        horizon = "swing" if "breakout_n" in prompt else "intraday"
        prompts[horizon] = prompt
        spec = swing_reply if horizon == "swing" else GAP
        return json.dumps({"strategies": [{"spec": spec, "thesis": horizon}]})

    out = await draft.run(db, redis, NOW, llm=llm, backtest=backtest_of(result()))
    assert set(prompts) == {"intraday", "swing"} and "orb_break" not in prompts["swing"]
    assert "breakout_n" not in prompts["intraday"]
    docs = await _drafts(db)
    assert out["drafted"] == 2 and len(out["passed"]) == 2
    horizons = sorted(d["spec"].get("horizon", "intraday") for d in docs.values())
    assert horizons == ["intraday", "swing"]
    # Next week each prompt shows only its own horizon's drafts.
    await draft.run(db, redis, NOW + timedelta(days=7), llm=llm, backtest=backtest_of(result()))
    swing_slug = next(s for s, d in docs.items() if d["spec"].get("horizon") == "swing")
    gap_slug = next(s for s in docs if s != swing_slug)
    assert swing_slug in prompts["swing"] and gap_slug not in prompts["swing"]
    assert gap_slug in prompts["intraday"] and swing_slug not in prompts["intraday"]


async def test_make_room_per_horizon(env):
    db, _, _ = env
    for i in range(5):
        await store.insert(db, {"slug": f"i{i}", "spec": ORB, "status": "active", "drafted_at": NOW - timedelta(days=9 - i)})
    for i in range(4):
        await store.insert(db, {"slug": f"s{i}", "spec": SWING, "status": "active", "drafted_at": NOW - timedelta(days=9 - i)})
    assert await draft._make_room(db, "swing") == []
    assert await draft._make_room(db, "intraday") == ["i0"]
    await store.insert(db, {"slug": "s4", "spec": SWING, "status": "active", "drafted_at": NOW})
    assert await draft._make_room(db, "swing") == ["s0"]
