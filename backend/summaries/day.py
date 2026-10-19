"""Home's "Your day": three plain lines (where you stand, what needs you, the
market), written twice a day per user -- with the 08:45 pre-market digest and
with the post-close digest after the 16:00 pass -- from those digests' own
numbers and the fact layer's market backdrop. Feature `portfolio`, fast tier."""

import logging
from datetime import datetime

from backend.engine.session import IST
from backend.prompts import render
from backend.summaries import core

logger = logging.getLogger(__name__)

KIND, PHASES = "day", {"pre": "before the market opens", "post": "after the market has closed"}
TTL = 30 * 3600
BRIEF_CHARS, MARKET_ROWS, NEEDS = 500, 5, 5


async def _market(db, redis) -> dict:
    from backend.ai.facts.market import market_backdrop

    m = await market_backdrop(db, redis, None)
    regime = m.get("regime") or {}
    return {"regime": regime.get("label"), "regime_score": regime.get("score"), "drivers": regime.get("drivers"),
            "brief": (m.get("brief") or "")[:BRIEF_CHARS],
            "markets": [{k: r.get(k) for k in ("name", "value", "percent")} for r in (m.get("markets") or [])[:MARKET_ROWS]]}


async def generate(db, redis, user_id: str, phase: str, now: datetime, digest_html: str):
    """The day summary for this user and phase ("pre" | "post"), once per IST day."""
    key = f"{now.astimezone(IST).date().isoformat()}:{phase}"

    async def build():
        from backend.portfolio import digest

        actions = await digest._actions(db, user_id, now)
        facts = {"account": core.plain(digest_html), "needs_you_count": len(actions),
                 "needs_you": [a["title"] for a in actions[:NEEDS]], "market": await _market(db, redis)}
        system, prompt = render(
            "summary_day", phase=PHASES[phase], account=facts["account"], count=len(actions),
            needs="\n".join(f"- {t}" for t in facts["needs_you"]) or "- nothing",
            market=core.as_facts(facts["market"]))
        return system, prompt, facts

    return await core.produce(db, redis, user_id, KIND, key, build, tier="fast", feature="portfolio",
                              ttl=TTL, max_lines=3)
