"""Attach a plain-language rationale to fresh suggestions.

The reason codes say which rule fired; they don't say why the company is
worth buying this week. ResearchAgent already produces exactly that
narrative for the analysis page, so suggestions reuse it rather than growing
a second, divergent explanation path.

This runs after the suggestions are already saved: the thesis is commentary,
and a slow or failing LLM must never be what stops a signal reaching the
inbox.
"""

import logging
from typing import Optional

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
            thesis = await _thesis_for(agent, suggestion["symbol"])
            if thesis:
                await store.attach_thesis(user_id, suggestion["id"], thesis)
                attached += 1
    return attached


async def _thesis_for(agent, symbol: str) -> Optional[str]:
    try:
        report = await agent.run(symbol)
    except Exception as exc:
        logger.warning("no thesis for %s: %s", symbol, exc)
        return None

    thesis = (getattr(report, "thesis", "") or getattr(report, "analyst_summary", "") or "").strip()
    if not thesis or thesis == "LLM_DISABLED":
        return None
    return thesis
