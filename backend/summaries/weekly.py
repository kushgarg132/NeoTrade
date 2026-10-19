"""The weekly report's narrative: what worked, what did not, one habit to watch.
Written with the report by the Sunday job (reports/weekly.py::send), once per user
per ISO week, from the report's own numbers and the journal's habit findings.
Feature `portfolio`, standard tier. Shown atop the Weekly report page and appended
to the Sunday Telegram text."""

import logging
from typing import Optional

from backend.prompts import render
from backend.summaries import core

logger = logging.getLogger(__name__)

KIND, TTL, PATTERNS = "weekly", 8 * 86_400, 3
PATTERN_KEYS = ("title", "trips", "pnl", "win_rate", "baseline_win_rate")


def _pct(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x * 100, 2)


def report_facts(r: dict) -> dict:
    """The report with returns as percentages, the unit the narrative states them in."""
    you, ideas = r["you"], r["ideas"]
    return {"you_return_pct": _pct(you["ret"]), "nifty_return_pct": _pct(you["nifty"]), "excess_pct": _pct(you["excess"]),
            "ai_book_return_pct": _pct(r["ai"]["ret"]), "best": r["best"], "worst": r["worst"],
            "ideas_taken": {"count": ideas["taken"]["n"], "avg_vs_nifty_pct": _pct(ideas["taken"]["mean_excess"])},
            "ideas_skipped": {"count": ideas["skipped"]["n"], "avg_vs_nifty_pct": _pct(ideas["skipped"]["mean_excess"])},
            "journal": r["journal"]}


async def generate(db, redis, user_id: str, report: dict):
    """The narrative for this report's week, or None (already written, or no usable model)."""
    async def build():
        from backend.ai.facts.user import journal

        found = (await journal(db, redis, user_id, period="month", account="mine")).get("patterns") or []
        patterns = [{k: p.get(k) for k in PATTERN_KEYS} | {"win_rate_pct": _pct(p.get("win_rate")),
                    "baseline_win_rate_pct": _pct(p.get("baseline_win_rate"))} for p in found[:PATTERNS]]
        for p in patterns:  # shown only in percent: one unit per figure
            p.pop("win_rate"), p.pop("baseline_win_rate")
        facts = {"report": report_facts(report), "patterns": patterns}
        system, prompt = render("summary_weekly", week=report["week"], report=core.as_facts(facts["report"]),
                                patterns=core.as_facts(patterns) if patterns else "none")
        return system, prompt, facts

    try:
        return await core.produce(db, redis, user_id, KIND, report["week"], build, tier="standard",
                                  feature="portfolio", ttl=TTL)
    except Exception as exc:
        logger.warning("weekly narrative failed for %s: %s", user_id, exc)
        return None
