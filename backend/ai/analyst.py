"""News analysis for one stock: fetch recent news, score it, write the note.

Two LLM calls per stock, down from up to eight:
1. `score_news` -- every article's relevance, sentiment and impact, plus the
   events they report, in one JSON response (was one call per article plus
   a separate events call over the same headlines).
2. `research_report` -- the sentiment report and the investment thesis in
   one Markdown response (the thesis used to be a second call rewriting the
   first).

The result is cached per symbol for CACHE_TTL_SECONDS and shared by every
caller (the AI analysis tab, suggestion theses, the analyst-verdict refresh)
and every user. The same run also fills `sentiment:{symbol}`, the cache the
engine and scan read for the AI half of conviction.

Sentiment is an impact- and recency-weighted average over *relevant* articles
only: weight = impact**2 * 0.5**(age_days / 30). Squared impact so a major
event (an earnings miss, impact 8) outweighs a minor piece (impact 4); a
30-day half-life because news on Indian mid-caps arrives weeks apart. A
3-day half-life was tried first and let one fresh promotional article
outvote a two-month-old 23% profit drop (Tata Elxsi, 2026-09-26: +0.60 vs
the report's own "Bearish"; this weighting gives -0.25). Irrelevant articles, and any the classifier did not return a valid
score for, are left out rather than counted as 0 -- counting them dragged
every stock's sentiment toward neutral.
"""

import asyncio
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.ai.sentiment import weighted_sentiment
from backend.routers.news import fetch_news_logic
from backend.core.models import FinancialEvent, NewsArticle
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

NEWS_LIMIT = 5
CACHE_TTL_SECONDS = 4 * 60 * 60
LAST_TTL_SECONDS = 7 * 24 * 3600  # outlives the 4h cache so the page can show the last read, marked stale
FRESH_IN_SESSION = 3600
THESIS_MARKER = "===THESIS==="

# Whoever sets this (the analysis websocket) receives {"type": "stage"|"delta", ...} as the note is made.
report_sink: ContextVar[Optional[Callable[[dict], None]]] = ContextVar("report_sink", default=None)


def emit(event: dict) -> None:
    sink = report_sink.get()
    if sink is not None:
        sink(event)


class AnalystOutput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    sentiment_score: float
    impact_score: int
    summary: str
    thesis: str = ""
    events: List[FinancialEvent]
    news_articles: List[Dict[str, Any]] = []  # Raw articles for UI display
    sentiment_analysis: Dict[str, Any] = {}  # Detailed breakdown


class _ArticleScore(BaseModel):
    index: int
    is_relevant: bool
    sentiment: Literal["POSITIVE", "NEGATIVE", "NEUTRAL"] = "NEUTRAL"
    score: float = Field(default=0.0, ge=-1.0, le=1.0)
    impact: int = Field(default=1, ge=0, le=10)


class _Event(BaseModel):
    event_type: str
    description: str
    impact_rating: int = Field(default=5, ge=0, le=10)


class _NewsScores(BaseModel):
    articles: List[_ArticleScore]
    events: List[_Event]


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    return text[start:end + 1]


async def _score_news(symbol: str, articles: List[NewsArticle]) -> Optional[_NewsScores]:
    """One call for every article and the events. Retried once; None if the
    model still does not return valid JSON in the expected shape."""
    listing = "\n\n".join(
        f"[{i}] {a.title}\n{(a.content or '')[:400]}" for i, a in enumerate(articles)
    )
    system, prompt = render("score_news", symbol=symbol, articles=listing)
    for attempt in (1, 2):
        # Deep: this score feeds every trade's AI share; Flash disagreed on 1 of 3 stocks.
        response = await llm_service.get_completion(prompt, system_prompt=system, tier="deep", feature="research")
        try:
            return _NewsScores.model_validate_json(_extract_json(response))
        except (ValueError, ValidationError) as exc:
            logger.warning("news scoring for %s: invalid response (attempt %d): %s", symbol, attempt, exc)
    return None


def _weighted_sentiment(scored: List[tuple[NewsArticle, _ArticleScore]], now: datetime) -> float:
    return weighted_sentiment(((a.published_at, s.score, s.impact) for a, s in scored), now) or 0.0


def _split_report(text: str) -> tuple[str, str]:
    if not text or text == "LLM_DISABLED" or text.startswith("Error generating response"):
        return "Unable to generate summary.", ""
    summary, _, thesis = text.partition(THESIS_MARKER)
    return summary.strip(), thesis.strip()


async def _report(**values) -> tuple[str, str]:
    """The research_report call: (summary, thesis), with the market brief
    (backend/datalayer/market.py) as backdrop so macro and global news
    reach every note."""
    from backend.datalayer.market import backdrop

    context = await backdrop(_redis())
    regime = context.get("regime") or {}
    values["backdrop"] = "\n".join(filter(None, [
        f"Risk regime: {regime['label']} ({regime['score']:+.2f})" if regime else "",
        context.get("brief") or "",
    ])) or "Not available."
    system, prompt = render("research_report", **values)
    try:
        if report_sink.get() is None:
            return _split_report(await llm_service.get_completion(prompt, system_prompt=system, tier="standard", feature="research"))
        parts = []
        async for delta in llm_service.stream_completion(prompt, system_prompt=system, tier="standard", feature="research"):
            parts.append(delta)
            if delta != "LLM_DISABLED" and not delta.startswith("Error generating response"):
                emit({"type": "delta", "text": delta})
        return _split_report("".join(parts))
    except Exception as e:
        logger.error(f"AnalystAgent LLM Error: {e}")
        return "Unable to generate summary.", ""


def _redis():
    from backend.database import db

    return db.redis


async def _write_note(redis, symbol: str, output: Dict[str, Any]) -> None:
    output["at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(output)
    await redis.set(f"analyst:{symbol}", body, ex=CACHE_TTL_SECONDS)
    await redis.set(f"analyst:last:{symbol}", body, ex=LAST_TTL_SECONDS)


async def latest(symbol: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The last stored read: {"read", "at", "stale"}. In session it is stale after
    FRESH_IN_SESSION; outside, once the 4h cache has expired. None when there is
    none or Redis is down."""
    from backend.core.market_calendar import market_phase

    redis = _redis()
    if redis is None:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        raw = await redis.get(f"analyst:last:{symbol}")
        if not raw:
            return None
        read = json.loads(raw)
        at = read["at"]
        if market_phase(now) == "session":
            stale = (now - datetime.fromisoformat(at)).total_seconds() > FRESH_IN_SESSION
        else:
            stale = await redis.get(f"analyst:{symbol}") is None
        return {"read": read, "at": at, "stale": stale}
    except Exception as exc:
        logger.warning("analyst last read failed for %s: %s", symbol, exc)
        return None


class AnalystAgent:
    async def analyze(self, state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["symbol"]
        # A socket refresh of a stale last read must not be answered by an older cached note.
        last = await latest(symbol) if report_sink.get() is not None else None
        last = last if last and last["stale"] else None
        out = await self._analyze_cached(symbol, last)
        if last and out.get("at") and datetime.fromisoformat(out["at"]) <= datetime.fromisoformat(last["at"]):
            # Same note handed back: stamp the last read so the next open sees it fresh.
            redis = _redis()
            try:
                await redis.set(f"analyst:last:{symbol}", json.dumps({**out, "at": datetime.now(timezone.utc).isoformat()}),
                                ex=LAST_TTL_SECONDS)
            except Exception as exc:
                logger.warning("analyst last restamp failed for %s: %s", symbol, exc)
        return out

    async def _analyze_cached(self, symbol: str, stale_last: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        from backend.datalayer.analysis import from_layer

        layered = await from_layer(symbol, self._cached, self._store_note)
        if layered is not None:
            return layered
        cached = None if stale_last else await self._cached(symbol)
        if cached is not None:
            logger.info("AnalystAgent: cache hit for %s", symbol)
            return cached

        from backend.datalayer.analysis import LOCK_SECONDS, WAIT_SECONDS

        # One run per stock: a loser waits for the winner's note rather than paying too.
        redis, owner = _redis(), False
        if redis is not None:
            try:
                owner = bool(await redis.set(f"analyst:lock:{symbol}", "1", nx=True, ex=LOCK_SECONDS))
                if not owner:
                    for _ in range(WAIT_SECONDS // 2):
                        await asyncio.sleep(2)
                        cached = await self._cached(symbol)
                        if cached is not None and (not stale_last or cached.get("at", "") > stale_last["at"]):
                            return cached
            except Exception as exc:
                logger.warning("analyst lock failed for %s: %s", symbol, exc)
        try:
            return await self._run(symbol)
        finally:
            if owner:
                try:
                    await redis.delete(f"analyst:lock:{symbol}")
                except Exception as exc:
                    logger.warning("analyst lock release failed for %s: %s", symbol, exc)

    async def _run(self, symbol: str) -> Dict[str, Any]:
        output = await self._analyze(symbol)
        # No news (or a failed fetch) cost no LLM calls; caching it would
        # only hide news that arrives later.
        # A failed score or report is not cached either: a blip would pin a neutral 0.0 for 4h.
        if output["news_articles"] and output["sentiment_analysis"].get("scored"):
            await self._store(symbol, output)
        return output

    async def _analyze(self, symbol: str) -> Dict[str, Any]:
        logger.info("AnalystAgent: analysing %s", symbol)
        try:
            articles = await fetch_news_logic(symbols=[symbol], limit=NEWS_LIMIT)
        except Exception as e:
            logger.error(f"AnalystAgent Error fetching news: {e}")
            return self._empty_output(symbol).model_dump(mode="json")
        articles = articles[:NEWS_LIMIT]
        if not articles:
            return self._empty_output(symbol).model_dump(mode="json")

        emit({"type": "stage", "step": "news", "count": len(articles)})
        scores = await _score_news(symbol, articles)
        by_index = {s.index: s for s in (scores.articles if scores else [])}
        relevant = []
        for i, article in enumerate(articles):
            score = by_index.get(i)
            if score is None or not score.is_relevant:
                article.sentiment, article.sentiment_score, article.impact_score = None, 0.0, 0
                continue
            article.sentiment = score.sentiment.lower()
            article.sentiment_score = score.score
            article.impact_score = score.impact
            relevant.append((article, score))

        now = datetime.now(timezone.utc)
        sentiment = _weighted_sentiment(relevant, now)
        max_impact = max((s.impact for _, s in relevant), default=0)
        raw_events = scores.events if scores else []
        events = [
            FinancialEvent(event_type=e.event_type, description=e.description, date=now,
                           symbols=[symbol], impact_rating=e.impact_rating)
            for e in raw_events
        ]

        news = "\n".join(
            f"- {a.title} ({s.sentiment.lower()}, impact {s.impact}): {(a.content or '')[:300]}"
            for a, s in relevant
        ) or "No relevant news found."
        emit({"type": "stage", "step": "writing"})
        summary, thesis = await _report(
            symbol=symbol, sentiment_score=f"{sentiment:.2f}", relevant_count=len(relevant), news=news,
            events=json.dumps([e.model_dump() for e in raw_events]),
        )

        scored = scores is not None and summary != "Unable to generate summary."
        label = "bullish" if sentiment > 0.15 else "bearish" if sentiment < -0.15 else "neutral"
        logger.info("AnalystAgent: %s sentiment %.2f from %d/%d relevant article(s)",
                    symbol, sentiment, len(relevant), len(articles))
        return AnalystOutput(
            symbol=symbol,
            sentiment_score=sentiment,
            impact_score=max_impact,
            summary=summary,
            thesis=thesis,
            events=events,
            news_articles=[a.model_dump(mode="json") for a in articles],
            sentiment_analysis={
                "score": round(sentiment, 2),
                "label": label,
                "risk_score": max_impact,  # Proxy for risk from news
                "article_count": len(articles),
                "relevant_count": len(relevant),
                "scored": scored,  # False: the LLM failed, sentiment_score 0.0 is "unknown", not neutral
            },
        ).model_dump(mode="json")

    async def _cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        redis = _redis()
        if redis is None:
            return None
        try:
            raw = await redis.get(f"analyst:{symbol}")
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("analyst cache read failed for %s: %s", symbol, exc)
            return None

    async def _store(self, symbol: str, output: Dict[str, Any]) -> None:
        redis = _redis()
        if redis is None:
            return
        try:
            await _write_note(redis, symbol, output)
            # The engine and scan read this for the AI half of conviction. The ingest
            # worker's blend lives 24h: never overwrite it with this 4h copy.
            if await redis.ttl(f"sentiment:{symbol}") <= CACHE_TTL_SECONDS:
                await redis.set(f"sentiment:{symbol}", output["sentiment_score"], ex=CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("analyst cache write failed for %s: %s", symbol, exc)

    async def _store_note(self, symbol: str, output: Dict[str, Any]) -> None:
        """The note only: for symbols the ingest worker follows, it owns
        `sentiment:{symbol}`."""
        redis = _redis()
        if redis is None:
            return
        try:
            await _write_note(redis, symbol, output)
        except Exception as exc:
            logger.warning("analyst cache write failed for %s: %s", symbol, exc)

    def _empty_output(self, symbol: str) -> AnalystOutput:
        return AnalystOutput(
            symbol=symbol,
            sentiment_score=0.0,
            impact_score=0,
            summary="No news found or error in analysis.",
            events=[],
            news_articles=[],
        )
