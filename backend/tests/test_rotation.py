"""The autopilot's weekly rotation (backend/autopilot/rotation.py): buys the
week's top ranks once, through the real fence; news and results only veto;
risk-off holds cash; with the autopilot off nothing is bought; the daily plan says so."""

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.autopilot import rotation, service
from backend.engine.session import IST
from backend.factor import data
from backend.factor.backtest import rebalance_days, simulate
from backend.factor.model import ROTATION, breadth

MONDAY = datetime(2026, 11, 9, 9, 21, tzinfo=IST)
BENCH = lambda: {"nifty": 26_000.0, "mom30": 50.0}
SYMBOLS = data.universe()[:40]
PREFS = {"user_id": "alice", "autopilot_enabled": True, "autopilot_live": False, "account_size": 200_000.0,
         "max_exposure": 200_000.0, "per_trade_cap": 30_000.0, "max_trades_per_day": 0, "daily_loss_limit": 0.0}


def _closes(days=400, crash=None, market_down=False):
    """Every symbol trends up at its own pace (later ones faster); `crash` drops one on the last day."""
    index = pd.bdate_range(end="2026-11-06", periods=days)
    rng = np.random.default_rng(0)
    cols = {}
    for i, s in enumerate(SYMBOLS):
        steps = 0.0002 * i + rng.normal(0, 0.01, days)
        cols[s] = 500 * np.exp(np.cumsum(steps))
    closes = pd.DataFrame(cols, index=index)
    if crash:
        closes.loc[closes.index[-1], crash] *= 0.8
    market = pd.Series(np.linspace(30_000, 20_000, days) if market_down else np.linspace(20_000, 26_000, days), index=index)
    return closes, market


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def set(self, key, value, nx=False, px=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, *keys):
        for k in keys:
            self.values.pop(k, None)

    async def mget(self, keys):
        return [self.values.get(k) for k in keys]


@pytest.fixture
def world(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    frame = {"closes": _closes()}

    async def marks(db_, symbols, **_):
        last = frame["closes"][0].iloc[-1]
        return {s: float(last[s]) for s in symbols if s in last}

    async def quiet(*a, **kw):
        return True

    async def regime_now(redis):
        return {}

    for mod in (service, rotation):
        monkeypatch.setattr(mod, "mark_prices", marks)
    monkeypatch.setattr(service, "_notify", quiet)
    monkeypatch.setattr(service, "regime_now", regime_now)
    monkeypatch.setattr(service, "in_session", lambda now: True)
    return db, frame


async def _prefs(db, **kw):
    await db["user_prefs"].insert_one({**PREFS, **kw})


async def _open(db):
    return {t["symbol"]: t for t in await db["paper_trades"].find({"status": "OPEN"}).to_list(None)}


async def test_buys_the_top_eight_once_equal_weight_through_the_fence(world):
    db, frame = world
    await _prefs(db)
    load = lambda: frame["closes"]
    results = await rotation.rebalance(db, FakeRedis(), "alice", MONDAY, load=load)
    assert [r["status"] for r in results] == ["FILLED"] * 8
    held = await _open(db)
    assert len(held) == 8 and all(t["strategy"] == "rotation" and t["via"] == "autopilot:rotation" for t in held.values())
    assert all(t["quantity"] * t["entry_price"] <= 25_000 for t in held.values())  # 1/8 of ₹2L, whole shares
    assert await rotation.rebalance(db, FakeRedis(), "alice", MONDAY, load=load) == []  # nothing left to do
    assert await db[rotation.TARGETS].count_documents({}) == 1


async def test_bad_news_and_results_veto_a_buy_only(world):
    db, frame = world
    await _prefs(db)
    load = lambda: frame["closes"]
    top = (await rotation.target(db, FakeRedis(), "bob", MONDAY, load=load))["ranks"][0]["symbol"]
    redis = FakeRedis({f"sentiment:{top}": json.dumps({"score": -0.8})})
    await rotation.rebalance(db, redis, "alice", MONDAY, load=load)
    held = await _open(db)
    assert top not in held and len(held) == 8  # the next name takes its slot
    doc = await db[rotation.TARGETS].find_one({"_id": f"alice:{rotation.week_of(MONDAY.date())}"})
    assert doc["news_vetoed"] == {top: "news sentiment -0.80"}


async def test_risk_off_holds_cash_and_autopilot_off_buys_nothing(world):
    db, frame = world
    await _prefs(db)
    frame["closes"] = _closes(market_down=True)
    assert await rotation.rebalance(db, FakeRedis(), "alice", MONDAY, load=lambda: frame["closes"]) == []
    p = await rotation.plan(db, FakeRedis(), "alice", MONDAY, load=lambda: frame["closes"], bench=BENCH)
    assert p["risk_off"] and "Risk-off" in rotation.plan_text(p)[0]

    frame["closes"] = _closes()
    await db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"autopilot_enabled": False}})
    nxt = MONDAY.replace(day=16)
    assert await rotation.rebalance(db, FakeRedis(), "alice", nxt, load=lambda: frame["closes"], buy=False) == []


async def test_risk_off_targets_nothing_and_sells_every_holding(world):
    db, frame = world
    await _prefs(db)
    await rotation.rebalance(db, FakeRedis(), "alice", MONDAY, load=lambda: frame["closes"])
    assert len(await _open(db)) == 8

    frame["closes"] = _closes(market_down=True)
    nxt = MONDAY.replace(day=16)
    load = lambda: frame["closes"]
    doc = await rotation.target(db, FakeRedis(), "alice", nxt, load=load)
    assert doc["weights"] == {} and doc["exposure"] == 0  # top ranks at weight 0 were read as "hold" and "buy"
    p = await rotation.plan(db, FakeRedis(), "alice", nxt, load=load, bench=BENCH)
    assert p["buys"] == [] and [s["why"] for s in p["sells"]] == ["risk_off"] * 8
    assert not any(line.startswith("Buy ") for line in rotation.plan_text(p))
    results = await rotation.rebalance(db, FakeRedis(), "alice", nxt, load=load)
    assert [r["status"] for r in results] == ["FILLED"] * 8
    assert await _open(db) == {}


async def test_daily_plan_lists_buys_holdings_and_next_rebalance(world):
    db, frame = world
    await _prefs(db)
    load = lambda: frame["closes"]
    p = await rotation.plan(db, FakeRedis(), "alice", MONDAY, load=load, bench=BENCH)
    assert len(p["buys"]) == 8 and p["holdings"] == [] and p["next_rebalance"] == "2026-11-16"
    await rotation.rebalance(db, FakeRedis(), "alice", MONDAY, load=load)
    p = await rotation.plan(db, FakeRedis(), "alice", MONDAY, load=load, bench=BENCH)
    assert len(p["holdings"]) == 8 and p["buys"] == []
    assert all(h["rank"] for h in p["holdings"])
    assert rotation.plan_text(p)[-1].startswith("Next rebalance 2026-11-16. Paper")


def test_weekly_rebalance_days_are_each_weeks_last_session():
    days = pd.bdate_range("2026-11-02", "2026-11-20")
    assert sorted(d.strftime("%d") for d in rebalance_days(days, "weekly")) == ["06", "13", "20"]


def test_backtest_runs_weekly_with_and_without_the_research_stop():
    from dataclasses import replace

    closes, market = _closes(crash=SYMBOLS[-1])
    assert breadth(closes, closes.index[-1]) > 0.5
    for params in (ROTATION, replace(ROTATION, stop_atr=3.0, breadth_min=0.4)):
        result = simulate(closes, market, params, closes.index[300], closes.index[-1], capital=200_000)
        assert result.rebalances >= 15 and np.isfinite(result.equity.iloc[-1])


def test_veto_outcome_compares_each_vetoed_name_with_the_book():
    closes, _ = _closes()
    start = closes.index[-6]
    a, b = SYMBOLS[0], SYMBOLS[1]
    prev = {"decided_on": str(start.date()), "news_vetoed": {a: "news sentiment -0.80", "NOPE": "results"},
            "weights": {b: 1.0}}
    out = rotation.veto_outcome(closes, prev)
    assert set(out["vetoed"]) == {a}  # a name with no prices is left out
    assert out["vetoed"][a] == round(float(closes[a].iloc[-1] / closes[a].loc[start] - 1), 4)
    assert out["book_avg"] == round(float(closes[b].iloc[-1] / closes[b].loc[start] - 1), 4)
    assert rotation.veto_outcome(closes, {**prev, "news_vetoed": {}}) is None


async def test_scorecard_from_daily_plans_and_veto_outcomes(world):
    from datetime import date

    db, _ = world
    rows = [("2026-11-02", 200_000, 26_000, 50), ("2026-11-03", 190_000, 25_800, 49), ("2026-11-04", 210_000, 26_260, 51)]
    await db[rotation.PLANS].insert_many([{"_id": f"alice:{d}", "user_id": "alice", "date": d, "book_value": v,
                                           "nifty": n, "mom30": m} for d, v, n, m in rows])
    await db[rotation.TARGETS].insert_one({"_id": "alice:2026-W45", "user_id": "alice",
                                           "veto_outcome": {"vetoed": {"X": -0.05, "Y": 0.04}, "book_avg": 0.01}})
    card = await rotation.scorecard(db, "alice", date(2026, 11, 4))
    assert card["book"] == 0.05 and card["nifty"] == 0.01 and card["mom30"] == 0.02
    assert card["max_drawdown"] == -0.05 and card["ahead"] and card["unlock_on"] == "2027-02-01"
    assert not card["live_ready"]  # ahead, but not three months yet
    assert card["vetoes"] == {"n": 2, "vetoed_avg": -0.005, "book_avg": 0.01, "helped": 1}
    assert await rotation.scorecard(db, "bob", date(2026, 11, 4)) is None


async def test_plan_snapshots_book_value_and_benchmarks(world):
    db, frame = world
    await _prefs(db)
    p = await rotation.plan(db, FakeRedis(), "alice", MONDAY, load=lambda: frame["closes"], bench=BENCH)
    assert p["book_value"] == 200_000 and p["nifty"] == 26_000.0 and p["mom30"] == 50.0
