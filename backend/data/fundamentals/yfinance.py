"""The working default FundamentalsProvider (Task 7) -- backed entirely by
the yfinance-derived `CompanyInfo` model that already exists (Task 1's
`fetch_stock_info_logic`), not a re-fetch of raw yfinance `.info`. No paid
fundamentals API key exists in this session (same constraint Task 5 hit for
Kite), so this is the real, working implementation; a second provider
against a paid schema (e.g. BharatStock) can be added later without touching
callers, since they only depend on the `FundamentalsProvider` protocol.
"""

import logging

from backend.datalayer.stock_info import fetch_stock_info_logic
from backend.instruments.models import Instrument
from backend.data.fundamentals.protocols import FundamentalSnapshot

logger = logging.getLogger(__name__)


def _debt_to_equity(total_debt, total_cash) -> float | None:
    """`CompanyInfo` doesn't carry shareholder equity, so this is really
    debt/cash, not debt/equity in the textbook sense -- the closest available
    leverage proxy given what yfinance's `.info` dict exposes. Only computed
    when both inputs are present and total_cash > 0; never fabricated from
    partial data."""
    if total_debt is None or total_cash is None or total_cash <= 0:
        return None
    return total_debt / total_cash


def _earnings_yield(pe_ratio) -> float | None:
    if pe_ratio is None or pe_ratio == 0:
        return None
    return 1.0 / pe_ratio


class YFinanceFundamentalsProvider:
    """Implements FundamentalsProvider on top of the existing yfinance
    pipeline. `snapshot()` re-resolves `instrument.tradingsymbol` through
    `fetch_stock_info_logic` (an indexed exact-match lookup, cheap) rather
    than duplicating its `.info` -> CompanyInfo mapping here."""

    async def snapshot(self, instrument: Instrument) -> FundamentalSnapshot | None:
        try:
            info = await fetch_stock_info_logic(instrument.tradingsymbol)
        except Exception as e:
            logger.warning(f"Fundamentals fetch failed for {instrument.tradingsymbol}: {e}")
            return None

        return FundamentalSnapshot(
            symbol=instrument.tradingsymbol,
            pe_ratio=info.pe_ratio,
            return_on_equity=info.return_on_equity,
            return_on_assets=info.return_on_assets,
            debt_to_equity=_debt_to_equity(info.total_debt, info.total_cash),
            revenue_growth=info.revenue_growth,
            earnings_yield=_earnings_yield(info.pe_ratio),
        )
