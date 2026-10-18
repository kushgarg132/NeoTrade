"""YFinanceFundamentalsProvider: mocked CompanyInfo fetch -> correct
FundamentalSnapshot mapping, including the debt_to_equity guard."""

from unittest.mock import AsyncMock, patch

from backend.core.models import CompanyInfo
from backend.instruments.models import Instrument
from backend.data.fundamentals.yfinance import YFinanceFundamentalsProvider

MODULE = "backend.data.fundamentals.yfinance"


def _instrument() -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol="RELIANCE", name="Reliance Industries",
        instrument_token=1, exchange_token=1, instrument_type="EQ", segment="NSE",
        lot_size=1, tick_size=0.05,
    )


def _company_info(**overrides) -> CompanyInfo:
    defaults = dict(
        symbol="RELIANCE.NS", name="Reliance Industries", current_price=2500.0,
        pe_ratio=20.0, return_on_equity=0.15, return_on_assets=0.08,
        revenue_growth=0.1, total_debt=1000.0, total_cash=500.0,
    )
    defaults.update(overrides)
    return CompanyInfo(**defaults)


async def test_snapshot_maps_full_company_info_correctly():
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(return_value=_company_info())):
        provider = YFinanceFundamentalsProvider()
        snapshot = await provider.snapshot(_instrument())

    assert snapshot is not None
    assert snapshot.symbol == "RELIANCE"
    assert snapshot.pe_ratio == 20.0
    assert snapshot.return_on_equity == 0.15
    assert snapshot.return_on_assets == 0.08
    assert snapshot.revenue_growth == 0.1
    assert snapshot.debt_to_equity == 2.0  # 1000 / 500
    assert snapshot.earnings_yield == 1.0 / 20.0


async def test_snapshot_debt_to_equity_none_when_total_cash_zero():
    info = _company_info(total_debt=1000.0, total_cash=0.0)
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(return_value=info)):
        snapshot = await YFinanceFundamentalsProvider().snapshot(_instrument())

    assert snapshot.debt_to_equity is None


async def test_snapshot_debt_to_equity_none_when_missing():
    info = _company_info(total_debt=None, total_cash=500.0)
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(return_value=info)):
        snapshot = await YFinanceFundamentalsProvider().snapshot(_instrument())

    assert snapshot.debt_to_equity is None


async def test_snapshot_earnings_yield_none_when_pe_missing_or_zero():
    info = _company_info(pe_ratio=None)
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(return_value=info)):
        snapshot = await YFinanceFundamentalsProvider().snapshot(_instrument())
    assert snapshot.earnings_yield is None

    info_zero = _company_info(pe_ratio=0.0)
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(return_value=info_zero)):
        snapshot = await YFinanceFundamentalsProvider().snapshot(_instrument())
    assert snapshot.earnings_yield is None


async def test_snapshot_returns_none_on_fetch_failure():
    with patch(f"{MODULE}.fetch_stock_info_logic", new=AsyncMock(side_effect=RuntimeError("boom"))):
        snapshot = await YFinanceFundamentalsProvider().snapshot(_instrument())

    assert snapshot is None
