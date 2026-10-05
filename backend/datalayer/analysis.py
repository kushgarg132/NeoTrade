"""AnalystAgent's answer built from the stored, already-scored news.

For a symbol the ingest worker follows (Nifty 200, held, watched) and while
its news loop is alive, the stock analysis no longer fetches or scores news
itself: it reads the newest scored company items from `news_items` and the
blended `sentiment:{SYM}`, and spends one LLM call on the written note --
only when newer news or a moved sentiment makes the cached note out of date.
Returns None whenever the layer cannot answer, and the caller falls back to
fetching on demand as before.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

NEWS_LIMIT = 5
NEWS_WINDOW = timedelta(days=30)
ALIVE_SECONDS = 15 * 60  # news_process beats every ~5 min
LOCK_SECONDS = 120
WAIT_SECONDS = 60


def _label(score: float) -> str:
    return "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"


async def _float(redis, key: str) -> Optional[float]:
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    value = value.get("score") if isinstance(value, dict) else value
    return float(value) if value is not None else None


async def from_layer(symbol: str, read_cached: Callable[[str], Awaitable[Optional[dict]]],
                     store: Callable[[str, dict], Awaitable[None]],
                     now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    from backend.database import db
    from backend.datalayer import news as layer
    from backend.datalayer.worker import HEARTBEAT_KEY

    mongo, redis = db.db, db.redis
    if mongo is None or redis is None:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        beat = await redis.get(HEARTBEAT_KEY.format("news_process"))
        if beat is None or now.timestamp() - int(beat) > ALIVE_SECONDS:
            return None
        names, sector_of = await layer.followed(mongo)
        if symbol not in names:
            return None
        docs = await mongo[layer.COLLECTION].find({
            "status": layer.SCORED, "published_at": {"$gte": now - NEWS_WINDOW},
            "impacts": {"$elemMatch": {"type": "symbol", "target": symbol}},
        }).sort("published_at", -1).limit(NEWS_LIMIT).to_list(length=None)
        sentiment = await _float(redis, f"sentiment:{symbol}") or 0.0
    except Exception as exc:
        logger.warning("analysis from the data layer failed for %s: %s", symbol, exc)
        return None

    basis = f"{docs[0]['_id'] if docs else '-'}:{sentiment:.2f}"
    cached = await read_cached(symbol)
    if cached and cached.get("basis") == basis:
        return cached

    # One writer per symbol; others wait for its note rather than paying too.
    if not await redis.set(f"analyst:lock:{symbol}", "1", nx=True, ex=LOCK_SECONDS):
        for _ in range(WAIT_SECONDS // 2):
            await asyncio.sleep(2)
            cached = await read_cached(symbol)
            if cached and cached.get("basis") == basis:
                return cached
    try:
        output = await _build(symbol, docs, sentiment, sector_of.get(symbol), redis)
        output["basis"] = basis
        await store(symbol, output)
        return output
    finally:
        await redis.delete(f"analyst:lock:{symbol}")


async def _build(symbol, docs, sentiment, sector, redis) -> Dict[str, Any]:
    from backend.components.analyst.agent import AnalystOutput, _report
    from backend.components.shared.models import FinancialEvent, NewsArticle

    articles, events, lines = [], [], []
    for doc in docs:
        hit = next(i for i in doc["impacts"] if i["type"] == "symbol" and i["target"] == symbol)
        direction, impact = float(hit["direction"]), int(round(hit["impact"]))
        articles.append(NewsArticle(
            title=doc["title"], url=doc.get("url", ""), source=doc.get("source", ""),
            published_at=doc["published_at"], content=doc.get("content") or None,
            sentiment="positive" if direction > 0.1 else "negative" if direction < -0.1 else "neutral",
            sentiment_score=direction, impact_score=impact, related_symbols=[symbol],
        ))
        events.append(FinancialEvent(event_type=doc.get("event") or "news", description=doc["title"],
                                     date=doc["published_at"], symbols=[symbol], impact_rating=impact))
        lines.append(f"- {doc['title']} ({_label(direction)}, impact {impact}): {(doc.get('content') or '')[:300]}")

    sector_score = await _float(redis, f"sector_sentiment:{sector}") if sector else None
    market_score = await _float(redis, "market:sentiment")
    context = [f"- Sector ({sector}) news sentiment: {sector_score:+.2f}" if sector_score is not None else "",
               f"- Indian market news sentiment: {market_score:+.2f}" if market_score is not None else ""]
    news = "\n".join(lines) or "No company-specific news in the last 30 days."
    news += "\n\nBackdrop:\n" + ("\n".join(c for c in context if c) or "- none scored yet")

    summary, thesis = await _report(
        symbol=symbol, sentiment_score=f"{sentiment:.2f}", relevant_count=len(docs), news=news,
        events=json.dumps([{"event_type": e.event_type, "description": e.description,
                            "impact_rating": e.impact_rating} for e in events]),
    )
    max_impact = max((a.impact_score for a in articles), default=0)
    return AnalystOutput(
        symbol=symbol, sentiment_score=sentiment, impact_score=max_impact, summary=summary, thesis=thesis,
        events=events, news_articles=[a.model_dump(mode="json") for a in articles],
        sentiment_analysis={
            "score": round(sentiment, 2), "label": _label(sentiment), "risk_score": max_impact,
            "article_count": len(articles), "relevant_count": len(articles),
            "sector_score": sector_score, "market_score": market_score,
        },
    ).model_dump(mode="json")
