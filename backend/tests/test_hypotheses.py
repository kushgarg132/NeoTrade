"""backend.learning.hypotheses: the LLM may only suggest threshold values
for a re-tunable strategy; each suggestion is queued and must pass the same
out-of-sample test and deflated Sharpe as the monthly re-tune grid."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.learning import hypotheses
from backend.learning.hypotheses import propose, validate
from backend.learning.retune import retune_strategy
from backend.strategies.registry import build_default_strategies
from backend.tests.test_retune import END, SPLIT, START, _backtester, _Strategy

NOW = datetime(2026, 11, 2, 11, tzinfo=timezone.utc)


def _strategies():
    return {s.spec.name: s for s in build_default_strategies(universe=["X"])}


def test_only_known_strategies_and_their_own_keys_within_bounds_pass():
    s = _strategies()
    ok = validate({"strategy": "macd_crossover", "params": {"stop_pct": 0.04}, "rationale": "r"}, s)
    assert ok == {"strategy": "macd_crossover", "params": {"stop_pct": 0.04, "target_pct": 0.06}, "rationale": "r"}
    assert validate({"strategy": "nope", "params": {"stop_pct": 0.04}}, s) is None
    # Intraday too, now that a year of 5-minute bars comes from Upstox.
    assert validate({"strategy": "volume_surge", "params": {"volume_mult": 4.5}}, s)["params"]["volume_mult"] == 4.5
    assert validate({"strategy": "macd_crossover", "params": {"leverage": 3}}, s) is None
    assert validate({"strategy": "macd_crossover", "params": {"stop_pct": 0.5}}, s) is None  # > 4x default
    assert validate({"strategy": "macd_crossover", "params": {"stop_pct": "wide"}}, s) is None
    assert validate({"strategy": "macd_crossover", "params": {"stop_pct": 0.03}}, s) is None  # what runs now
    assert validate({"strategy": "macd_crossover", "params": {"stop_pct": 0.02}}, s) is None  # already in the grid


@pytest.mark.asyncio
async def test_propose_queues_at_most_three_valid_ideas(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    answer = {"hypotheses": [
        {"strategy": "macd_crossover", "params": {"stop_pct": 0.04}, "rationale": "stops too tight"},
        {"strategy": "macd_crossover", "params": {"leverage": 9}, "rationale": "bad key"},
        {"strategy": "mean_reversion", "params": {"rsi_max": 28.0}, "rationale": "a"},
        {"strategy": "technical_breakout", "params": {"volume_mult": 1.8}, "rationale": "b"},
        {"strategy": "technical_breakout", "params": {"target_r": 2.5}, "rationale": "c"},
    ]}
    llm = AsyncMock(return_value="Here:\n" + json.dumps(answer))
    monkeypatch.setattr(hypotheses.llm_service, "get_completion", llm)

    queued = await propose(db, _strategies(), NOW)
    assert [q["strategy"] for q in queued] == ["macd_crossover", "mean_reversion", "technical_breakout"]
    stored = await db["strategy_hypotheses"].find({}).to_list(10)
    assert len(stored) == 3 and {d["status"] for d in stored} == {"queued"}
    assert "macd_crossover" in llm.call_args.args[0]  # the prompt names what may be tuned


@pytest.mark.asyncio
async def test_a_model_that_answers_badly_queues_nothing(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(hypotheses.llm_service, "get_completion", AsyncMock(return_value="LLM_DISABLED"))
    assert await propose(db, _strategies(), NOW) == []
    assert await db["strategy_hypotheses"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_a_hypothesis_is_judged_like_any_variant():
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 50, 4.0: 900})
    win = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[],
                                candidates=[{"volume_mult": 4.0}])
    assert win["accepted"] and win["trials"] == 1

    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 300, 4.0: -200})
    lose = await retune_strategy(_Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, past_trials=[0.1] * 9,
                                 candidates=[{"volume_mult": 4.0}])
    assert not lose["accepted"] and "out of sample" in lose["reason"] and lose["trials"] == 10


@pytest.mark.asyncio
async def test_test_queued_settles_each_hypothesis_and_records_the_attempt():
    db = AsyncMongoMockClient()["t"]
    await db["strategy_hypotheses"].insert_many([
        {"id": "h1", "strategy": "volume_surge", "params": {"volume_mult": 4.0}, "rationale": "r",
         "status": "queued", "created_at": NOW},
        {"id": "h2", "strategy": "other", "params": {"volume_mult": 4.0}, "status": "queued", "created_at": NOW},
    ])
    bt = _backtester({2.0: -100, 3.0: 100, 4.0: 900}, {2.0: 0, 3.0: 50, 4.0: 900})
    docs = await hypotheses.test_queued(db, _Strategy, bt, {"volume_mult": 3.0}, START, SPLIT, END, [], NOW)

    assert [d["accepted"] for d in docs] == [True]
    h1 = await db["strategy_hypotheses"].find_one({"id": "h1"})
    assert h1["status"] == "accepted" and h1["tested_at"] == NOW
    assert (await db["strategy_hypotheses"].find_one({"id": "h2"}))["status"] == "queued"
    retune = await db["strategy_retunes"].find_one({"hypothesis_id": "h1"})
    assert retune["accepted"] and retune["params"] == {"volume_mult": 4.0} and retune["source"] == "hypothesis"
