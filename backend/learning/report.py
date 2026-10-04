"""What the learning loop knows, for a person: the rules it follows now,
what it changed and why, and every setup's record. The figures are
deterministic; the weekly Telegram note has the LLM explain them
(prompt: backend/prompts/learning_review.md) and falls back to the
figures alone when no model answers. It never decides anything.
"""

import logging
from datetime import datetime, timedelta

from backend.learning.adapt import _closed_trades, _state, load_rules
from backend.learning.attribution import attribute
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

CHANGES_DAYS = 30
MAX_GROUPS = 25


async def snapshot(db, user_id: str, nifty: list, now: datetime) -> dict:
    rules = await load_rules(db, user_id)
    rows = attribute(await _closed_trades(db, user_id, (await _state(db, user_id))["reset_at"]), nifty)
    changes = await db["learning_changes"].find(
        {"user_id": user_id, "at": {"$gte": now - timedelta(days=CHANGES_DAYS)}}, {"_id": 0, "user_id": 0},
    ).sort("at", -1).to_list(50)
    return {
        "rules": {"paused": sorted(rules.paused), "floors": rules.floors,
                  "skip_regimes": rules.skip_regimes, "regime_today": rules.regime},
        "changes": changes,
        "groups": sorted(rows, key=lambda r: r["net"])[:MAX_GROUPS],
    }


def _group_line(r: dict) -> str:
    pf = "—" if r["profit_factor"] is None else f"{r['profit_factor']:.2f}"
    setup = "overall" if r["by"] == "all" else f"{r['by']} {r['group']}"
    return (f"{r['strategy']} / {setup}: n {r['trades']}, net ₹{r['net']:,.0f}, win {r['win_rate']:.0%}, "
            f"exp ₹{r['expectancy']:,.0f}, shrunk ₹{r['shrunk']:,.0f}, pf {pf}")


def _change_line(c: dict) -> str:
    ev = c.get("evidence") or {}
    why = f" ({ev['by']} {ev.get('group') or ''}: n {ev['trades']}, net ₹{ev['net']:,.0f})" if "trades" in ev else ""
    return f"{c['strategy']}: {c['rule']} {c['before']} → {c['after']}{why}"


def facts(snap: dict) -> dict:
    r = snap["rules"]
    rules = "\n".join(filter(None, [
        f"Paused: {', '.join(r['paused'])}" if r["paused"] else "",
        "Strength floors: " + ", ".join(f"{k} {v:.2f}" for k, v in r["floors"].items()) if r["floors"] else "",
        "Skipped regimes: " + ", ".join(f"{k} {'/'.join(v)}" for k, v in r["skip_regimes"].items()) if r["skip_regimes"] else "",
        f"Nifty regime today: {r['regime_today'] or 'unknown'}",
    ]))
    return {
        "rules": rules,
        "changes": "\n".join(_change_line(c) for c in snap["changes"]) or "none",
        "groups": "\n".join(_group_line(g) for g in snap["groups"]),
    }


async def weekly_text(db, user_id: str, nifty: list, now: datetime):
    """The Friday note, or None when the user has no closed paper trades."""
    snap = await snapshot(db, user_id, nifty, now)
    if not snap["groups"]:
        return None
    f = facts(snap)
    system, prompt = render("learning_review", **f)
    try:
        text = (await llm_service.get_completion(prompt, system_prompt=system, tier="standard") or "").strip()
    except Exception as exc:
        logger.warning("learning review: model failed: %s", exc)
        text = ""
    head = "🧠 What the paper engine learned this week"
    return f"{head}\n\n{text}" if text else f"{head}\n\n{f['rules']}\n\nChanges:\n{f['changes']}\n\nWorst setups:\n{f['groups']}"
