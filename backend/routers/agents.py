from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging

from backend.research.graph import ResearchAgent, ResearchReport
from backend.research.quick import QuickAnalysis, quick_analysis

logger = logging.getLogger(__name__)

router = APIRouter()
research_agent = ResearchAgent()


@router.post("/quick-analyze/{symbol}", response_model=QuickAnalysis)
async def quick_analyze_stock(symbol: str):
    """Non-AI counterpart to /analyze/{symbol}: quote, fundamentals, and
    price-based technicals only, no LLM call. HTTP fallback for the `quick_analyze`
    websocket action (see backend/ws/routes.py) when the socket isn't up yet."""
    try:
        return await quick_analysis(symbol)
    except Exception as e:
        logger.error(f"Error in quick analysis for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The analysis failed; try again in a minute.")

class AnalyzeRequest(BaseModel):
    symbol: str
    account_size: float = 100000.0
    current_exposure: float = 0.0

@router.post("/analyze/{symbol}", response_model=ResearchReport)
async def analyze_stock(symbol: str, request: AnalyzeRequest = None):
    """
    Generate a research report (company info, news/sentiment, LLM thesis) for
    a given stock symbol. NOTE: this endpoint no longer produces a trade
    decision or signal -- see backend.scoring.composite / backend.strategies
    for that. account_size/current_exposure are accepted for request-body
    backward compatibility but are no longer used by the research pipeline.
    """
    logger.info(f"Received analyze request for {symbol}")

    try:
        result = await research_agent.run(symbol)
        logger.info(f"Research report complete for {symbol}")
        return result
    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The analysis failed; try again in a minute.")
