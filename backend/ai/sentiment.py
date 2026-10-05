"""AI sentiment off the engine's hot path.

The engine loop (backend/engine/runner.py, Task 6) must never await an LLM
round-trip synchronously -- a per-bar decision blocking on an LLM call is a
latency and reliability risk no trading loop should carry. So sentiment is
computed out-of-band -- by AnalystAgent (backend/components/analyst/agent.py),
which writes `sentiment:{symbol}` whenever it analyses a stock -- and the
engine only ever reads the cache (`get_cached_sentiment`), which returns None on a miss rather than
blocking or raising. backend.scoring.composite.score_intent already treats
None as neutral (0.0).
"""

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


async def get_cached_sentiment(symbol: str, redis) -> Optional[float]:
    """Reads a Redis-cached sentiment score. Returns None (never blocks on the
    LLM, never raises) if no fresh value is cached -- score_intent above
    already treats None as 0.0/neutral, which is a safe default: an engine
    loop must never let an optional cache dependency take it down, whether
    that's a cache miss or Redis being unreachable outright."""
    key = f"sentiment:{symbol}"
    try:
        val = await redis.get(key)
    except Exception as exc:
        logger.warning("sentiment cache unavailable for %s: %s", symbol, exc)
        return None
    return float(val) if val is not None else None


# 30-day half-life: news on Indian mid-caps arrives weeks apart, and a
# 3-day one let a fresh puff piece outvote a two-month-old 23% profit drop
# (see backend/components/analyst/agent.py).
RECENCY_HALF_LIFE_DAYS = 30.0


def weighted_sentiment(points: Iterable[tuple[datetime, float, float]], now: datetime) -> Optional[float]:
    """Impact- and recency-weighted mean of (published_at, score -1..1,
    impact 0..10) points: weight = impact**2 * 0.5**(age_days / 30), so one
    major event outweighs several minor pieces. None with no points."""
    total = weight_sum = 0.0
    for published, score, impact in points:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - published).total_seconds() / 86400)
        weight = max(impact, 1) ** 2 * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        total += weight * score
        weight_sum += weight
    return total / weight_sum if weight_sum else None
