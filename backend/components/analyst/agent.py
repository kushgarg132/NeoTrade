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

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.ai.sentiment import weighted_sentiment
from backend.components.analyst.news import fetch_news_logic
from backend.components.shared.models import FinancialEvent, NewsArticle
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

NEWS_LIMIT = 5
CACHE_TTL_SECONDS = 4 * 60 * 60
THESIS_MARKER = "===THESIS==="


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
    articles: List[_ArticleScore] = []
    events: List[_Event] = []


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
        response = await llm_service.get_completion(prompt, system_prompt=system, tier="deep")
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
        return _split_report(await llm_service.get_completion(prompt, system_prompt=system, tier="standard"))
    except Exception as e:
        logger.error(f"AnalystAgent LLM Error: {e}")
        return "Unable to generate summary.", ""


def _redis():
    from backend.database import db

    return db.redis


class AnalystAgent:
    async def analyze(self, state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["symbol"]
        from backend.datalayer.analysis import from_layer

        layered = await from_layer(symbol, self._cached, self._store_note)
        if layered is not None:
            return layered
        cached = await self._cached(symbol)
        if cached is not None:
            logger.info("AnalystAgent: cache hit for %s", symbol)
            return cached

        output = await self._analyze(symbol)
        # No news (or a failed fetch) cost no LLM calls; caching it would
        # only hide news that arrives later.
        if output["news_articles"]:
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
        summary, thesis = await _report(
            symbol=symbol, sentiment_score=f"{sentiment:.2f}", relevant_count=len(relevant), news=news,
            events=json.dumps([e.model_dump() for e in raw_events]),
        )

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
            await redis.set(f"analyst:{symbol}", json.dumps(output), ex=CACHE_TTL_SECONDS)
            # The engine and scan read this for the AI half of conviction.
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
            await redis.set(f"analyst:{symbol}", json.dumps(output), ex=CACHE_TTL_SECONDS)
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
