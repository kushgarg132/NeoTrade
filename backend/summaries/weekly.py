"""The weekly report's narrative: what worked, what did not, one habit to watch.
Written with the report by the Sunday job (reports/weekly.py::send), once per user
per ISO week, from the report's own numbers and the journal's habit findings.
Feature `portfolio`, standard tier. Shown atop the Weekly report page and appended
to the Sunday Telegram text."""

import logging
from backend.prompts import render
from backend.summaries import core

logger = logging.getLogger(__name__)

KIND, TTL, PATTERNS = "weekly", 8 * 86_400, 3
PATTERN_KEYS = ("title", "trips", "pnl", "win_rate", "baseline_win_rate")


def report_facts(r: dict) -> dict:
    """The report with returns as percentages, the unit the narrative states them in."""
    you, ideas = r["you"], r["ideas"]
    return {"you_return_pct": core.pct(you["ret"]), "nifty_return_pct": core.pct(you["nifty"]), "excess_pct": core.pct(you["excess"]),
            "ai_book_return_pct": core.pct(r["ai"]["ret"]), "best": r["best"], "worst": r["worst"],
            "ideas_taken": {"count": ideas["taken"]["n"], "avg_vs_nifty_pct": core.pct(ideas["taken"]["mean_excess"])},
            "ideas_skipped": {"count": ideas["skipped"]["n"], "avg_vs_nifty_pct": core.pct(ideas["skipped"]["mean_excess"])},
            "journal": r["journal"]}


def news_facts(r: dict) -> dict:
    """The week's news attribution (portfolio/news_moves.py::week), titles and figures only."""
    news = r.get("news") or {}
    return {"big_movers": [{"symbol": m["symbol"], "move_pct": m["move_pct"], "vs_nifty_pct": m["vs_nifty"],
                            "news": [{"title": i["title"], "scope": i["scope"], "direction": i["direction"]} for i in m["items"]]}
                           for m in news.get("movers") or []],
            "themes": news.get("themes") or [],
            "accuracy_5d_hit_pct": news.get("accuracy")}


async def generate(db, redis, user_id: str, report: dict):
    """The narrative for this report's week, or None (already written, or no usable model)."""
    async def build():
        from backend.ai.facts.user import journal

        found = (await journal(db, redis, user_id, period="month", account="mine")).get("patterns") or []
        patterns = [{k: p.get(k) for k in PATTERN_KEYS} | {"win_rate_pct": core.pct(p.get("win_rate")),
                    "baseline_win_rate_pct": core.pct(p.get("baseline_win_rate"))} for p in found[:PATTERNS]]
        for p in patterns:  # shown only in percent: one unit per figure
            p.pop("win_rate"), p.pop("baseline_win_rate")
        facts = {"report": report_facts(report), "patterns": patterns, "news": news_facts(report)}
        system, prompt = render("summary_weekly", week=report["week"], report=core.as_facts(facts["report"]),
                                patterns=core.as_facts(patterns) if patterns else "none",
                                news=core.as_facts(facts["news"]))
        return system, prompt, facts

    try:
        return await core.produce(db, redis, user_id, KIND, report["week"], build, tier="standard",
                                  feature="portfolio", ttl=TTL)
    except Exception as exc:
        logger.warning("weekly narrative failed for %s: %s", user_id, exc)
        return None
