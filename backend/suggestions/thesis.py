"""Attach a plain-language rationale to fresh suggestions.

The reason codes say which rule fired; they don't say why the company is
worth buying this week. ResearchAgent already produces exactly that
narrative for the analysis page, so suggestions reuse it rather than growing
a second, divergent explanation path.

This runs after the suggestions are already saved: the thesis is commentary,
and a slow or failing LLM must never be what stops a signal reaching the
inbox.

The same research run also measures news sentiment, and that reading is the
AI half of the suggestion's conviction. At scan time the sentiment cache is
empty (it is only filled after the scan, and expires in 15 minutes), so
every suggestion was scored with AI = 0 (neutral), capping conviction at
0.7 x rule + 0.15. The score is recomputed here with the same
CompositeScore formula once a real reading exists.
"""

import logging
from typing import Optional

from backend.scoring.composite import CompositeScore
from backend.suggestions.store import SuggestionStore

logger = logging.getLogger(__name__)

# One LLM round trip per suggestion, so a scan of a wide universe on a
# volatile day can't turn into a hundred of them.
MAX_PER_SCAN = 10


async def attach_theses(db, user_id: str, suggestions: list[dict], agent=None, limit: int = MAX_PER_SCAN) -> int:
    if not suggestions:
        return 0

    if agent is None:
        from backend.research.graph import ResearchAgent
        agent = ResearchAgent()

    from backend.llm import use_model
    from backend.prefs import PrefsStore
    prefs = await PrefsStore(db).get(user_id)

    store = SuggestionStore(db)
    attached = 0
    with use_model(prefs.get("omniroute_model")):
        for suggestion in suggestions[:limit]:
            try:
                report = await agent.run(suggestion["symbol"])
            except Exception as exc:
                logger.warning("no thesis for %s: %s", suggestion["symbol"], exc)
                continue
            thesis = _thesis_text(report)
            score = _rescored(suggestion.get("score"), report)
            await store.attach_thesis(user_id, suggestion["id"], thesis, score=score)
            if thesis:
                attached += 1
    return attached


def _thesis_text(report) -> Optional[str]:
    thesis = (getattr(report, "thesis", "") or getattr(report, "analyst_summary", "") or "").strip()
    if not thesis or thesis == "LLM_DISABLED":
        return None
    return thesis


def _rescored(score: Optional[dict], report) -> Optional[dict]:
    """The stored score with its AI half set from this report's sentiment.
    None when there is nothing to update: no stored score, or no reading."""
    sentiment = getattr(report, "sentiment_score", None)
    if not score or sentiment is None:
        return None
    composite = CompositeScore(rule_score=score["rule"], ai_score=max(-1.0, min(1.0, float(sentiment))))
    return {"rule": composite.rule_score, "ai": composite.ai_score, "final": composite.final}
