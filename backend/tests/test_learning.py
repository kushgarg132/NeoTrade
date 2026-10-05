"""backend.learning: judging closed paper trades by setup, and the bounded
rules learned from them (pause, per-strategy floor, regime skip)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.learning import adapt
from backend.learning.adapt import LearnedRules, decide, learn, load_rules
from backend.learning.attribution import PRIOR_TRADES, attribute, regime_on, shrunk

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
START = date(2025, 1, 1)


def _nifty(days: int = 400, falling_from: int | None = None) -> list:
    """Rising Nifty; falling hard from day `falling_from` if given."""
    points, close = [], 20000.0
    for i in range(days):
        close += -150.0 if falling_from is not None and i >= falling_from else 10.0
        points.append((START + timedelta(days=i), close))
    return points


def _trade(net: float, strategy: str = "vwap", strength: float = 0.7, reason: str = "dip",
           day: int = 300) -> dict:
    entry = datetime.combine(START + timedelta(days=day), datetime.min.time(), tzinfo=timezone.utc)
    return {
        "strategy": strategy, "venue": "paper", "status": "CLOSED", "realized_pnl": net + 20.0,
        "costs": 20.0, "entry_at": entry, "exit_at": entry + timedelta(hours=2),
        "context": {"strength": strength, "reason_codes": [reason], "score": {}},
    }


def _row(rows, strategy, by, group=None):
    return next(r for r in rows if r["strategy"] == strategy and r["by"] == by and r["group"] == group)


def test_a_few_lucky_trades_barely_move_the_shrunk_expectancy():
    assert shrunk([1000.0] * 3) == pytest.approx(3000.0 / (3 + PRIOR_TRADES))
    assert shrunk([1000.0] * 3) < 0.25 * 1000.0
    assert shrunk([]) == 0.0


def test_regime_is_up_above_the_200_dma_and_down_below_it():
    nifty = _nifty(falling_from=250)
    assert regime_on(START + timedelta(days=240), nifty) == "up"
    assert regime_on(START + timedelta(days=300), nifty) == "down"
    assert regime_on(START + timedelta(days=50), nifty) is None  # not 200 closes yet


def test_attribution_is_net_of_costs_and_groups_by_setup():
    trades = [_trade(100.0)] * 12 + [_trade(-100.0, strength=0.5, reason="gap")] * 12
    rows = attribute(trades, _nifty())

    everything = _row(rows, "vwap", "all")
    assert everything["trades"] == 24 and everything["net"] == pytest.approx(0.0)
    assert _row(rows, "vwap", "reason", "gap")["net"] == pytest.approx(-1200.0)
    assert _row(rows, "vwap", "strength", "<0.6")["expectancy"] == pytest.approx(-100.0)
    assert _row(rows, "vwap", "regime", "up")["trades"] == 24


def test_small_groups_are_not_reported():
    rows = attribute([_trade(100.0)] * 12 + [_trade(-50.0, reason="rare")] * 3, _nifty())
    assert not [r for r in rows if r["group"] == "rare"]
    assert _row(rows, "vwap", "all")["trades"] == 15  # the overall row always is


def test_a_strategy_losing_over_30_trades_is_paused_but_not_before():
    state = adapt.empty_state()
    assert not [c for c in decide(state, attribute([_trade(-100.0)] * 29, _nifty())) if c["rule"] == "pause"]
    changes = decide(state, attribute([_trade(-100.0)] * 30, _nifty()))
    assert [c["strategy"] for c in changes if c["rule"] == "pause"] == ["vwap"]


def test_losing_weak_signals_raise_that_strategys_floor_one_bounded_step():
    trades = [_trade(-80.0, strength=0.5)] * 12 + [_trade(150.0, strength=0.85)] * 12
    state = adapt.empty_state()
    [change] = [c for c in decide(state, attribute(trades, _nifty())) if c["rule"] == "floor"]
    assert change["before"] == pytest.approx(0.45) and change["after"] == pytest.approx(0.50)

    state["floors"]["vwap"] = 0.6  # already above the losing bucket: nothing left to cut
    assert not [c for c in decide(state, attribute(trades, _nifty())) if c["rule"] == "floor"]


def test_the_floor_never_passes_its_cap():
    trades = [_trade(-80.0, strength=0.7)] * 12 + [_trade(150.0, strength=0.9)] * 12
    state = adapt.empty_state()
    state["floors"]["vwap"] = adapt.FLOOR_CAP - 0.01
    [change] = [c for c in decide(state, attribute(trades, _nifty())) if c["rule"] == "floor"]
    assert change["after"] == pytest.approx(adapt.FLOOR_CAP)


def test_a_strategy_that_loses_only_in_one_regime_skips_that_regime():
    nifty = _nifty(falling_from=250)
    trades = [_trade(120.0, day=240)] * 12 + [_trade(-100.0, day=320)] * 12
    changes = decide(adapt.empty_state(), attribute(trades, nifty))
    assert [(c["rule"], c["after"]) for c in changes] == [("regime", ["down"])]


def test_learned_rules_block_paused_weak_and_wrong_regime_signals():
    rules = LearnedRules(paused={"orb"}, floors={"vwap": 0.6}, skip_regimes={"macd": ["down"]}, regime="down")
    assert rules.blocks("orb", 0.9)
    assert rules.blocks("vwap", 0.55)
    assert not rules.blocks("vwap", 0.65)
    assert rules.blocks("macd", 0.9)
    assert not rules.blocks(None, 0.9)
    assert not LearnedRules(skip_regimes={"macd": ["down"]}, regime="up").blocks("macd", 0.9)


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def _insert(db, trades, user_id="alice"):
    await db["paper_trades"].insert_many([{**t, "user_id": user_id} for t in trades])


@pytest.mark.asyncio
async def test_learn_pauses_logs_and_is_read_back_as_rules(db):
    await _insert(db, [_trade(-100.0)] * 30)
    changes = await learn(db, "alice", _nifty(), NOW)

    assert [c["rule"] for c in changes] == ["pause"]
    logged = await db["learning_changes"].find({"user_id": "alice"}).to_list(10)
    assert logged[0]["strategy"] == "vwap" and logged[0]["at"] == NOW
    assert (await load_rules(db, "alice")).blocks("vwap", 0.9)
    assert await learn(db, "alice", _nifty(), NOW) == []  # already paused: no repeat


@pytest.mark.asyncio
async def test_old_trades_without_context_borrow_it_from_their_suggestion(db):
    trade = {**_trade(-100.0, strength=0.5), "context": None, "suggestion_id": "s1"}
    await _insert(db, [trade] * 12 + [_trade(150.0, strength=0.9)] * 12)
    await db["suggestions"].insert_one({"id": "s1", "user_id": "alice", "strength": 0.5, "reason_codes": ["x"]})
    changes = await learn(db, "alice", _nifty(), NOW)
    assert [c["rule"] for c in changes] == ["floor"]


@pytest.mark.asyncio
async def test_a_paused_strategy_returns_after_a_newer_passing_gate_and_forgets_old_trades(db):
    await _insert(db, [_trade(-100.0)] * 30)
    await learn(db, "alice", _nifty(), NOW)
    await db["strategy_backtests"].insert_one(
        {"strategy_name": "vwap", "passed": True, "run_at": NOW + timedelta(days=1)})

    later = NOW + timedelta(days=2)
    changes = await learn(db, "alice", _nifty(), later)
    assert [c["rule"] for c in changes] == ["resume"]
    assert not (await load_rules(db, "alice")).blocks("vwap", 0.9)
    assert await learn(db, "alice", _nifty(), later + timedelta(days=1)) == []  # old losses no longer count


@pytest.mark.asyncio
async def test_other_users_trades_are_never_learned_from(db):
    await _insert(db, [_trade(-100.0)] * 30, user_id="bob")
    assert await learn(db, "alice", _nifty(), NOW) == []
    assert not await db["learning_changes"].find_one({"user_id": "alice"})


@pytest.mark.asyncio
async def test_the_nightly_pass_stores_todays_regime_for_runs(db):
    await learn(db, "alice", _nifty(falling_from=250), NOW)
    assert (await load_rules(db, "alice")).regime == "down"


@pytest.mark.asyncio
async def test_the_daily_pass_learns_for_every_user_with_paper_trades(db, monkeypatch):
    from backend import scheduler
    from backend.portfolio import service

    async def nifty():
        return _nifty()

    monkeypatch.setattr(service, "_nifty", nifty)
    await _insert(db, [_trade(-100.0)] * 30)
    await _insert(db, [_trade(-100.0)] * 30, user_id="bob")
    assert await scheduler._learn(db, NOW) == 2


@pytest.mark.asyncio
async def test_the_weekly_note_says_nothing_without_trades(db):
    from backend.learning.report import weekly_text
    assert await weekly_text(db, "alice", _nifty(), NOW) is None


@pytest.mark.asyncio
async def test_the_weekly_note_falls_back_to_the_figures_when_no_model_answers(db, monkeypatch):
    from unittest.mock import AsyncMock

    from backend.learning import report

    await _insert(db, [_trade(-100.0)] * 30)
    await learn(db, "alice", _nifty(), NOW)
    monkeypatch.setattr(report.llm_service, "get_completion", AsyncMock(return_value=""))
    text = await report.weekly_text(db, "alice", _nifty(), NOW)
    assert "Paused: vwap" in text and "vwap: pause False → True" in text and "net ₹-3,000" in text


@pytest.mark.asyncio
async def test_the_weekly_note_is_the_models_explanation_when_it_answers(db, monkeypatch):
    from unittest.mock import AsyncMock

    from backend.learning import report

    await _insert(db, [_trade(-100.0)] * 30)
    llm = AsyncMock(return_value="What lost money: vwap.")
    monkeypatch.setattr(report.llm_service, "get_completion", llm)
    text = await report.weekly_text(db, "alice", _nifty(), NOW)
    assert text.endswith("What lost money: vwap.")
    assert "vwap / overall: n 30" in llm.call_args.args[0]


def test_the_journal_learning_endpoint_shows_rules_changes_setups_and_retunes(monkeypatch):
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.auth.dependency import get_current_user
    from backend.auth.models import User
    from backend.routers import journal as journal_router

    mock_db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(journal_router.db, "db", mock_db)

    async def setup():
        await _insert(mock_db, [_trade(-100.0)] * 30)
        await _insert(mock_db, [_trade(-100.0, strategy="orb")] * 30, user_id="bob")
        await learn(mock_db, "alice", _nifty(), datetime.now(timezone.utc))
        await mock_db["strategy_retunes"].insert_many([
            {"strategy": "macd_crossover", "at": NOW - timedelta(days=40), "accepted": True,
             "params": {"stop_pct": 0.05}, "current": {"stop_pct": 0.03}, "reason": "won", "trial_sharpes": [0.1]},
            {"strategy": "macd_crossover", "at": NOW, "accepted": False,
             "params": {"stop_pct": 0.02}, "current": {"stop_pct": 0.05}, "reason": "deflated Sharpe 0.40",
             "trial_sharpes": [0.2]},
        ])
        await mock_db["strategy_hypotheses"].insert_one({"id": "h1", "strategy": "macd_crossover", "status": "queued",
                                                         "params": {"stop_pct": 0.04}, "rationale": "r", "created_at": NOW})
    asyncio.run(setup())
    app = FastAPI()
    app.include_router(journal_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: User(
        id="alice", google_sub="g", email="a@x.io", name="A", created_at=NOW)
    app.dependency_overrides[journal_router.get_nifty] = _nifty

    body = TestClient(app).get("/api/v1/journal/learning").json()
    assert body["rules"]["paused"] == ["vwap"]
    assert [c["rule"] for c in body["changes"]] == ["pause"]
    assert {g["strategy"] for g in body["groups"]} == {"vwap"}  # never bob's
    [retune] = body["retunes"]
    assert retune["strategy"] == "macd_crossover" and retune["reason"] == "deflated Sharpe 0.40"
    assert retune["running"] == {"stop_pct": 0.05} and "trial_sharpes" not in retune
    assert [h["status"] for h in body["hypotheses"]] == ["queued"]
