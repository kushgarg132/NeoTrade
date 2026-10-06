from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

# Enums
class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"

class Trend(str, Enum):
    UP = "up"
    DOWN = "down"
    CHOPPY = "choppy"

class NewsArticle(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    title: str
    url: str
    source: str
    published_at: datetime
    content: Optional[str] = None
    sentiment: Optional[Sentiment] = None
    sentiment_score: float = 0.0  # -1.0 to 1.0
    impact_score: int = 0  # 1-10
    related_symbols: List[str] = []

class FinancialEvent(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    event_type: str  # earnings, merger, layoff, etc.
    description: str
    date: datetime
    symbols: List[str]
    impact_rating: int

class PriceCandle(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adj_close: Optional[float] = None
    volume: float

class BacktestResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[Dict[str, Any]] # List of individual trade details


class CompanyInfo(BaseModel):
    """Comprehensive stock/company information for UI display"""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    current_price: float
    previous_close: Optional[float] = None
    day_change: Optional[float] = None
    day_change_percent: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    currency: str = "USD"  # Default to USD

    logo_url: Optional[str] = None
    
    # Fundamental Data
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    trailing_eps: Optional[float] = None
    forward_eps: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    revenue_growth: Optional[float] = None
    total_revenue: Optional[float] = None
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    ebitda: Optional[float] = None
    operating_margins: Optional[float] = None
    gross_margins: Optional[float] = None

    gross_margins: Optional[float] = None


class Watchlist(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    
    user_id: str
    symbols: List[str] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)
