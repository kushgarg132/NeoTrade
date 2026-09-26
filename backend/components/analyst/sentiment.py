from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import asyncio
import logging
import json

from backend.components.shared.models import NewsArticle, Sentiment
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

router = APIRouter()

class SentimentAnalysisRequest(BaseModel):
    articles: List[NewsArticle]

class SentimentAnalysisResponse(BaseModel):
    analyzed_articles: List[NewsArticle]

@router.post("/news/sentiment", response_model=SentimentAnalysisResponse)
async def analyze_sentiment(request: SentimentAnalysisRequest):
    """
    Analyzes the sentiment of the provided news articles using an LLM.
    Updates the sentiment, sentiment_score, and impact_score fields.
    """
    analyzed = await analyze_sentiment_logic(request.articles)
    return SentimentAnalysisResponse(analyzed_articles=analyzed)

async def analyze_sentiment_logic(articles: List[NewsArticle], target_symbol: str = None) -> List[NewsArticle]:
    logger.info(f"Analyzing sentiment for {len(articles)} articles (Target: {target_symbol})")

    # Each article's LLM call is independent -- gather() so a click on a
    # stock waits for the slowest one call (~4s), not the sum of all of them
    # in series (~4s * article count, on top of the events/summary/thesis
    # calls the rest of the research pipeline still makes after this).
    analyzed = await asyncio.gather(*(_analyze_one(article, target_symbol) for article in articles))

    logger.info(f"Sentiment analysis complete for {len(analyzed)} articles")
    return list(analyzed)


async def _analyze_one(article: NewsArticle, target_symbol: str = None) -> NewsArticle:
    logger.debug(f"Processing article: {article.title[:50] if article.title else 'No Title'}...")

    # Construct prompt - handle None content
    content_preview = (article.content or "")[:500]  # Increased context

    system, prompt = render(
        "article_sentiment",
        target=target_symbol or "GENERAL MARKET",
        relevance_target=target_symbol or "finance",
        headline=article.title,
        content=content_preview,
    )

    try:
        response = await llm_service.get_completion(
            prompt,
            system_prompt=system
        )

        if response == "LLM_DISABLED":
            # Mock fallback
            article.sentiment = Sentiment.NEUTRAL
            article.sentiment_score = 0.0
            article.impact_score = 1
        else:
            # Clean response
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            data = json.loads(response.strip())

            # Check relevance first
            if not data.get("is_relevant", True) and target_symbol:
                logger.info(f"Article skipped due to low relevance: {article.title[:30]}...")
                article.sentiment = Sentiment.NEUTRAL
                article.sentiment_score = 0.0
                article.impact_score = 0
                # We could strictly remove it, but keeping it as NEUTRAL/0 impact is safer for now
            else:
                try:
                    article.sentiment = Sentiment(data.get("sentiment", "neutral").lower())
                except ValueError:
                    article.sentiment = Sentiment.NEUTRAL

                article.sentiment_score = float(data.get("score", 0.0))
                article.impact_score = int(data.get("impact", 0))
                # Store reasoning? Models don't have reasoning field yet.
                # We could append it to content or summary later. For now, it just improves the score quality.

            logger.debug(f"Sentiment result: {article.sentiment}, score: {article.sentiment_score}")

    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        article.sentiment = Sentiment.NEUTRAL

    return article
