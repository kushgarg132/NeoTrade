"""Analyst-verdict cache for AnalystVerdictStrategy -- mirrors backend/ai/sentiment.py's
get_cached_sentiment's read-only-cache shape: the engine loop (and, here, the daily
scan) must never await an LLM round-trip synchronously, so the real AnalystAgent call happens
out-of-band (refresh_analyst_verdict, called by the scheduler -- see backend/scheduler.py)
and is cached in Redis; callers only ever read the cache (get_cached_verdict), which returns
None on a miss or any Redis error rather than blocking or raising.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_cached_verdict(symbol: str, redis) -> Optional[dict]:
    """Reads a Redis-cached analyst verdict. Returns None (never blocks on the LLM, never
    raises) on a cache miss, a Redis failure, or a malformed cached value."""
    key = f"analyst_verdict:{symbol}"
    try:
        val = await redis.get(key)
    except Exception as exc:
        logger.warning("analyst verdict cache unavailable for %s: %s", symbol, exc)
        return None
    if val is None:
        return None
    try:
        parsed = json.loads(val)
    except (TypeError, ValueError):
        logger.warning("analyst verdict cache for %s held a malformed value", symbol)
        return None
    if not isinstance(parsed, dict):
        logger.warning("analyst verdict cache for %s held a non-dict value", symbol)
        return None
    return parsed


async def refresh_analyst_verdict(symbol: str, redis, ttl_seconds: int = 90000) -> dict:
    """Computes a fresh verdict (via the existing AnalystAgent) and writes it to Redis with
    the given TTL. 90000s (25h) means yesterday's verdict survives comfortably until the next
    scheduled refresh even if that run is a little early or late. Called by a background
    task/job (backend.scheduler), never by the engine loop or a Strategy directly.

    `top_reason` is a short catalyst string, not the full LLM narrative: the highest-impact
    event's description if any events were classified, otherwise the first non-empty line of
    the summary (truncated to 200 chars).
    """
    from backend.components.analyst.agent import AnalystAgent

    output = await AnalystAgent().analyze({"symbol": symbol})

    events = output.get("events") or []
    if events:
        top_event = max(events, key=lambda e: e.get("impact_rating", 0))
        top_reason = top_event.get("description", "")[:200]
    else:
        summary = output.get("summary") or ""
        top_reason = next((line.strip() for line in summary.splitlines() if line.strip()), "")[:200]

    verdict = {
        "sentiment_score": float(output.get("sentiment_score", 0.0)),
        "impact_score": int(output.get("impact_score", 0)),
        "label": output.get("sentiment_analysis", {}).get("label", "neutral"),
        "top_reason": top_reason,
    }

    key = f"analyst_verdict:{symbol}"
    await redis.set(key, json.dumps(verdict), ex=ttl_seconds)
    logger.info("Refreshed analyst verdict for %s: %s", symbol, verdict["label"])
    return verdict
