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
    async def backtest(strategy, start, end):
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


async def test_backtest_failure_leaves_that_draft_testing_and_tests_the_next(env):
    db, redis, _ = env
    tested = []

    async def backtest(strategy, start, end):
        tested.append(strategy.spec.name)
        if len(tested) == 1:
            raise TimeoutError("history gap")
        return result()

    out = await draft.run(db, redis, NOW, llm=llm_of(GAP, ORB), backtest=backtest)
    statuses = {d["slug"]: d["status"] for d in (await _drafts(db)).values()}
    first = tested[0].removeprefix("built:")
    assert len(tested) == 2 and statuses[first] == "testing" and out["drafted"] == 2
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
