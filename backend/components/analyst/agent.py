# import httpx - removed
from typing import List, Dict, Any
from pydantic import BaseModel, ConfigDict
from backend.components.shared.models import NewsArticle, FinancialEvent
from backend.llm import llm_service
from backend.prompts import render
from backend.configs.settings import settings
import logging

logger = logging.getLogger(__name__)

class AnalystOutput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    sentiment_score: float
    impact_score: int
    summary: str
    events: List[FinancialEvent]
    news_articles: List[Dict[str, Any]] = []  # Raw articles for UI display
    sentiment_analysis: Dict[str, Any] = {} # Detailed breakdown

from backend.components.analyst.news import fetch_news_logic
from backend.components.analyst.sentiment import analyze_sentiment_logic
from backend.components.analyst.events import classify_events_logic

class AnalystAgent:
    def __init__(self):
        pass
        # self.base_url was removed as we use direct tool calls now
        
    async def analyze(self, state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state['symbol']
        logger.info(f"AnalystAgent: Starting analysis for {symbol}")
        """
        Orchestrates the news analysis workflow:
        1. Fetch News
        2. Analyze Sentiment
        3. Detect Events
        4. Synthesize Summary
        """
        # 1. Fetch News
        try:
            # Use tool logic directly (Pythonic tool usage)
            articles = await fetch_news_logic(symbols=[symbol], limit=5)
            # articles is List[NewsArticle]
        except Exception as e:
            logger.error(f"AnalystAgent Error fetching news: {e}")
            return self._empty_output(symbol).model_dump(mode='json')

        if not articles:
            return self._empty_output(symbol).model_dump(mode='json')

        # 2. Analyze Sentiment
        try:
            # Logic function takes List[NewsArticle] and returns List[NewsArticle]
            analyzed_articles_objs = await analyze_sentiment_logic(articles, target_symbol=symbol)
            # Convert to list of dicts for state/UI
            analyzed_articles = [a.model_dump(mode='json') for a in analyzed_articles_objs]
        except Exception as e:
                logger.error(f"AnalystAgent Error analyzing sentiment: {e}")
                analyzed_articles = [a.model_dump(mode='json') for a in articles] # Fallback to raw articles

        # 3. Detect Events (from concatenated text or titles)
        combined_text = "\n".join([f"{a['title']}: {(a.get('content') or '')[:100]}" for a in analyzed_articles])
        events = []
        try:
            # Logic function takes text and date, returns List[FinancialEvent]
            from datetime import datetime
            events_objs = await classify_events_logic(combined_text, datetime.now())
            events = [e.model_dump(mode='json') for e in events_objs]
        except Exception as e:
            logger.error(f"AnalystAgent Error classifying events: {e}")

        # 4. Synthesize Summary using LLM with Chain of Thought
        system, summary_prompt = render(
            "analyst_summary", symbol=symbol, news=combined_text[:3000], events=events,
        )

        try:
            summary = await llm_service.get_completion(summary_prompt, system_prompt=system)
        except Exception as e:
            logger.error(f"AnalystAgent LLM Error: {e}")
            summary = "Unable to generate summary due to LLM error."

        # Calculate aggregate scores
        avg_sentiment = sum(a.get('sentiment_score', 0) for a in analyzed_articles) / len(analyzed_articles) if analyzed_articles else 0
        max_impact = max([a.get('impact_score', 0) for a in analyzed_articles] + [0])
        
        # Determine Label
        if avg_sentiment > 0.15:
            label = "bullish"
        elif avg_sentiment < -0.15:
            label = "bearish"
        else:
            label = "neutral"
            
        sentiment_analysis = {
            "score": float(f"{avg_sentiment:.2f}"),
            "label": label,
            "risk_score": max_impact, # Proxy for risk from news
            "article_count": len(analyzed_articles)
        }
        
        logger.info(f"AnalystAgent: Analysis complete for {symbol}. Sentiment: {avg_sentiment:.2f}")
        return AnalystOutput(
            symbol=symbol,
            sentiment_score=avg_sentiment,
            impact_score=max_impact,
            summary=summary,
            events=[FinancialEvent(**e) for e in events],
            news_articles=analyzed_articles,
            sentiment_analysis=sentiment_analysis
        ).model_dump(mode='json')

    def _empty_output(self, symbol: str) -> AnalystOutput:
        return AnalystOutput(
            symbol=symbol,
            sentiment_score=0.0,
            impact_score=0,
            summary="No news found or error in analysis.",
            events=[],
            news_articles=[]
        )
