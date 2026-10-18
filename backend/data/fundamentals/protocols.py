"""Fundamentals-provider protocol for the long-term quality screen (Task 7).

Same shape as Task 5's Kite scaffolding: one Protocol, one real implementation
backed by whatever data source is actually available in this session
(yfinance-derived `CompanyInfo`, free, no key needed -- see
backend/data/fundamentals/yfinance.py), with room for a second
implementation against a paid provider's schema later without touching any
caller.
"""

from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict

from backend.instruments.models import Instrument


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    pe_ratio: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_yield: Optional[float] = None


class FundamentalsProvider(Protocol):
    async def snapshot(self, instrument: Instrument) -> Optional[FundamentalSnapshot]: ...
