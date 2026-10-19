"""Money > Journal > Habits: "What your trades say", a few sentences once per user per ISO
week from the journal's own behaviour findings (journal/insights.py through the journal fact)
and the all-time cost picture. Written in the daily pass on the week's last trading day.
Feature `learning`, standard tier. Describes; never says what to trade."""

import logging
from datetime import date

from backend.prompts import render
from backend.reports.weekly import week_id
from backend.summaries import core
from backend.summaries.weekly import PATTERN_KEYS

logger = logging.getLogger(__name__)

KIND, TTL, PATTERNS = "habits", 8 * 86_400, 5
COST_KEYS = ("gross_pnl", "charges", "net_pnl", "trades_per_year", "heavy_trader")


async def generate(db, redis, user_id: str, week: str):
    async def build():
        from backend.ai.facts.user import journal

        every = await journal(db, redis, user_id, period="all", account="mine")
        this_week = await journal(db, redis, user_id, period="week", account="mine")
        patterns = [{k: p.get(k) for k in PATTERN_KEYS if k not in ("win_rate", "baseline_win_rate")}
                    | {"win_rate_pct": core.pct(p.get("win_rate")), "baseline_win_rate_pct": core.pct(p.get("baseline_win_rate")),
                       "avg_pnl": p.get("avg_pnl")} for p in (every.get("patterns") or [])[:PATTERNS]]
        if not patterns and not this_week.get("closed"):
            return None  # nothing found and nothing closed this week
        week_facts = {"closed_this_week": this_week.get("closed"), "wins_this_week": this_week.get("wins"),
                      "gross_pnl_this_week": this_week.get("pnl_gross"), "closed_all_time": every.get("closed"),
                      "costs_all_time": {k: (every.get("costs_all_time") or {}).get(k) for k in COST_KEYS}}
        system, prompt = render("summary_habits", patterns=core.as_facts(patterns) if patterns else "none yet",
                                week=core.as_facts(week_facts))
        return system, prompt, {"patterns": patterns, "week": week_facts}

    return await core.produce(db, redis, user_id, KIND, week, build, tier="standard", feature="learning", ttl=TTL)


async def run_all(db, redis, pass_day: date) -> int:
    """Every user with journal trades, for the ISO week `pass_day` falls in."""
    written = 0
    for user_id in sorted(await db["journal_trades"].distinct("user_id")):
        try:
            written += bool(await generate(db, redis, user_id, week_id(pass_day)))
        except Exception as exc:
            logger.warning("habits summary failed for %s: %s", user_id, exc)
    return written
