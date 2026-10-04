"""The LLM's ideas for a strategy's thresholds, queued and then tested like
any re-tune variant (backend/learning/retune.py): an idea runs only if it
wins on the year it was never chosen on and passes the deflated Sharpe,
counting every variant and idea ever tried for that strategy.

The LLM never changes anything itself. It sees the strategies' current
thresholds, the last re-tune's in-sample results and every user's paper
setups, and may only suggest numbers for keys a strategy already has, within
BOUND of what runs now. Prompt: backend/prompts/strategy_hypotheses.md.
"""

import json
import logging
import re
import uuid
from datetime import datetime

from backend.learning.attribution import attribute
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

MAX_PER_RUN = 3
BOUND = 4.0  # a value may be at most 4x, or at least 1/4 of, the current one
MAX_SETUPS = 15


def validate(idea: dict, strategies: dict) -> dict | None:
    """The idea with its params merged over what runs now, or None when it
    names an unknown or untestable strategy or key, a value out of bounds,
    or something the grid already tries."""
    from backend.learning.retune import WINDOW_DAYS, variants

    strategy = strategies.get(idea.get("strategy")) if isinstance(idea, dict) else None
    params = idea.get("params") if strategy is not None else None
    if not isinstance(params, dict) or not params or strategy.spec.timeframe not in WINDOW_DAYS:
        return None
    for key, value in params.items():
        now = strategy.p.get(key)
        if now is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if now > 0 and not (now / BOUND <= value <= now * BOUND):
            return None
    merged = {**strategy.p, **{k: float(v) for k, v in params.items()}}
    if merged == strategy.p or merged in variants(strategy.GRID):
        return None
    return {"strategy": strategy.spec.name, "params": merged, "rationale": str(idea.get("rationale") or "")[:300]}


async def _all_paper_trades(db) -> list[dict]:
    from backend.learning.adapt import _closed_trades, _state

    trades = []
    for user_id in await db["paper_trades"].distinct("user_id"):
        trades += await _closed_trades(db, user_id, (await _state(db, user_id))["reset_at"])
    return trades


async def propose(db, strategies: dict, now: datetime) -> list[dict]:
    """Asks the model for ideas and queues the valid ones. A model that is
    off or answers badly queues nothing."""
    from backend.learning.retune import WINDOW_DAYS
    from backend.portfolio.service import _nifty

    tunable = {n: s for n, s in strategies.items() if getattr(s, "GRID", None) and s.spec.timeframe in WINDOW_DAYS}
    retunes = []
    for name in tunable:
        last = await db["strategy_retunes"].find_one({"strategy": name, "train": {"$exists": True}}, sort=[("at", -1)])
        retunes += [f"{name} {variant}: {summary}" for variant, summary in ((last or {}).get("train") or {}).items()]
    trades = await _all_paper_trades(db)
    rows = sorted(attribute(trades, await _nifty() if trades else []), key=lambda r: r["net"])[:MAX_SETUPS]
    system, prompt = render(
        "strategy_hypotheses",
        strategies="\n".join(f"{n}: runs {s.p}; grid {s.GRID}" for n, s in tunable.items()),
        retunes="\n".join(retunes) or "none yet",
        setups="\n".join(
            f"{r['strategy']} / {r['by']} {r['group'] or ''}: n {r['trades']}, net ₹{r['net']:,.0f}, "
            f"exp ₹{r['expectancy']:,.0f}, pf {r['profit_factor']}" for r in rows) or "none yet",
    )
    text = await llm_service.get_completion(prompt, system_prompt=system, tier="deep") or ""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        ideas = json.loads(match.group(0)).get("hypotheses") if match else None
    except (json.JSONDecodeError, AttributeError):
        ideas = None
    if not isinstance(ideas, list):
        logger.warning("hypotheses: no usable answer from the model: %.200s", text)
        return []

    queued = []
    for idea in ideas:
        valid = validate(idea, tunable)
        if valid and valid["params"] not in [q["params"] for q in queued]:
            queued.append({**valid, "id": str(uuid.uuid4()), "status": "queued", "created_at": now})
        if len(queued) == MAX_PER_RUN:
            break
    if queued:
        await db["strategy_hypotheses"].insert_many([dict(q) for q in queued])
    return queued


async def test_queued(db, strategy, backtest, current: dict, start, split, end, past_trials: list[float],
                      now: datetime) -> list[dict]:
    """Tests every queued idea for `strategy`, records each attempt in
    `strategy_retunes` (accepted ones become what runs) and settles the
    idea. Returns the attempts."""
    from backend.learning.retune import retune_strategy

    docs = []
    for idea in await db["strategy_hypotheses"].find({"strategy": strategy.spec.name, "status": "queued"}).to_list(None):
        try:
            doc = await retune_strategy(strategy, backtest, current, start, split, end, past_trials,
                                        candidates=[idea["params"]])
        except Exception as exc:
            logger.exception("testing hypothesis %s failed", idea["id"])
            doc = {"strategy": strategy.spec.name, "accepted": False, "params": idea["params"], "reason": f"failed: {exc}"}
        doc.update(at=now, source="hypothesis", hypothesis_id=idea["id"])
        await db["strategy_retunes"].insert_one(dict(doc))
        await db["strategy_hypotheses"].update_one({"id": idea["id"]}, {"$set": {
            "status": "accepted" if doc["accepted"] else "rejected", "reason": doc["reason"], "tested_at": now}})
        past_trials = past_trials + doc.get("trial_sharpes", [])
        if doc["accepted"]:
            current = doc["params"]
        docs.append(doc)
    return docs
