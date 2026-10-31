from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging

from backend.auth.dependency import get_current_user
from backend.auth.models import User

from backend.research.graph import ResearchAgent, ResearchReport
from backend.research.quick import QuickAnalysis, quick_analysis

logger = logging.getLogger(__name__)

router = APIRouter()
research_agent = ResearchAgent()


@router.post("/quick-analyze/{symbol}", response_model=QuickAnalysis)
async def quick_analyze_stock(symbol: str, user: User = Depends(get_current_user)):
    """Non-AI counterpart to /analyze/{symbol}: quote, fundamentals, and
    price-based technicals only, no LLM call. HTTP fallback for the `quick_analyze`
    websocket action (see backend/ws/routes.py) when the socket isn't up yet."""
    from backend.database import db
    from backend.rate_limit import allow

    # Same per-user budget as the socket's quick_analyze action.
    if not await allow(db.redis, f"quick_analyze:{user.id}", 60, 60):
        raise HTTPException(status_code=429, detail="Too many requests in a minute; wait a moment and try again.")
    try:
        return await quick_analysis(symbol)
    except Exception as e:
        logger.error(f"Error in quick analysis for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The analysis failed; try again in a minute.")

@router.get("/intraday/{symbol}")
async def intraday_candles(symbol: str, days: int = 1):
    """Intraday candles for the stock chart: `days=1` the latest session at 5 minutes (today's while
    the market is open, else the last trading day's; 1D), `days=5` five sessions at 15 minutes (1W)."""
    from backend.datalayer import stock_info

    if days not in stock_info.INTRADAY_WINDOWS:
        raise HTTPException(status_code=422, detail="days must be 1 or 5")
    period, interval = stock_info.INTRADAY_WINDOWS[days]
    candles, _ = await stock_info.fetch_price_history_logic(symbol, period=period, interval=interval)
    return [c.model_dump(mode="json") for c in candles]

class AnalyzeRequest(BaseModel):
    symbol: str
    account_size: float = 100000.0
    current_exposure: float = 0.0

@router.post("/analyze/{symbol}", response_model=ResearchReport)
async def analyze_stock(symbol: str, request: AnalyzeRequest = None, user: User = Depends(get_current_user)):
    """
    Generate a research report (company info, news/sentiment, LLM thesis) for
    a given stock symbol. NOTE: this endpoint no longer produces a trade
    decision or signal -- see backend.scoring.composite / backend.strategies
    for that. account_size/current_exposure are accepted for request-body
    backward compatibility but are no longer used by the research pipeline.
    """
    logger.info(f"Received analyze request for {symbol}")

    from backend.database import db
    from backend.llm import LIMIT_MESSAGE, DailyLimitReached, use_model
    from backend.prefs import PrefsStore
    from backend.rate_limit import allow

    # The socket's own limits, which this HTTP fallback skipped: the user's
    # daily LLM cap (use_model bills the user) and a per-minute budget.
    if not await allow(db.redis, f"analyze:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many analyses: try again in a minute.")
    try:
        prefs = await PrefsStore(db.db).get(user.id)
        with use_model(prefs.get("omniroute_model"), user_id=user.id):
            result = await research_agent.run(symbol)
        logger.info(f"Research report complete for {symbol}")
        return result
    except DailyLimitReached:
        raise HTTPException(status_code=429, detail=LIMIT_MESSAGE)
    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The analysis failed; try again in a minute.")
