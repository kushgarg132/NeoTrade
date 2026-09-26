"""backend.research.quick.quick_analysis: the non-AI stock snapshot -- no
LLM call, so nothing here should ever touch backend.llm."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.components.shared.models import CompanyInfo, PriceCandle
from backend.instruments.models import Instrument
from backend.research import quick as quick_module

MODULE = "backend.research.quick"


def _instrument() -> Instrument:
    return Instrument(
        exchange="NSE", tradingsymbol="RELIANCE", name="Reliance Industries",
        instrument_token=1, exchange_token=1, instrument_type="EQ", segment="NSE",
        lot_size=1, tick_size=0.05,
    )


def _candles(n=260, base=2000.0):
    now = datetime.now(timezone.utc)
    return [
        PriceCandle(
            symbol="RELIANCE.NS",
            timestamp=now - timedelta(days=n - i),
            open=base + i, high=base + i + 5, low=base + i - 5, close=base + i,
            volume=1_000_000,
        )
        for i in range(n)
    ]


def _company_info() -> CompanyInfo:
    return CompanyInfo(symbol="RELIANCE", name="Reliance Industries", current_price=2500.0)


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(
        f"{MODULE}.resolve_company_query",
        AsyncMock(return_value={"symbol": "RELIANCE", "peers": ["TCS"], "name": "Reliance Industries"}),
    )
    monkeypatch.setattr(f"{MODULE}.resolve_symbol", AsyncMock(return_value=_instrument()))
    monkeypatch.setattr(f"{MODULE}.get_database", AsyncMock(return_value=object()))
    monkeypatch.setattr(f"{MODULE}.InstrumentMaster", lambda db: object())
    monkeypatch.setattr(f"{MODULE}.fetch_stock_info_logic", AsyncMock(return_value=_company_info()))
    candles = _candles()
    monkeypatch.setattr(quick_module._provider, "history", AsyncMock(return_value=candles))
    return candles


async def test_quick_analysis_never_calls_the_llm(wired, monkeypatch):
    llm_spy = AsyncMock(side_effect=AssertionError("quick_analysis must not call the LLM"))
    monkeypatch.setattr("backend.llm.llm_service.get_completion", llm_spy)

    result = await quick_module.quick_analysis("RELIANCE")

    llm_spy.assert_not_called()
    assert result.symbol == "RELIANCE"
    assert result.company_info["symbol"] == "RELIANCE"
    assert result.peers == ["TCS"]


async def test_quick_analysis_returns_price_data_and_technicals(wired):
    result = await quick_module.quick_analysis("RELIANCE")

    assert len(result.price_data) == len(wired)
    assert result.technical_analysis["rsi"] is not None
    assert result.technical_analysis["sma_200"] is not None


async def test_quick_analysis_handles_no_price_history(wired, monkeypatch):
    monkeypatch.setattr(quick_module._provider, "history", AsyncMock(return_value=[]))

    result = await quick_module.quick_analysis("RELIANCE")

    assert result.price_data == []
    assert result.technical_analysis == {}


async def test_resolving_a_stock_makes_no_llm_call_unless_peers_are_asked_for():
    """The LLM peer lookup was ~10s of a ~11s stock search, for data no
    screen displays. It must stay opt-in."""
    from backend.components.master import search

    instrument = MagicMock(tradingsymbol="RELIANCE", name="Reliance Industries")
    with patch(f"{search.__name__}.resolve_symbol", AsyncMock(return_value=instrument)), \
         patch(f"{search.__name__}.get_database", AsyncMock(return_value=MagicMock())), \
         patch(f"{search.__name__}._find_peers", AsyncMock(return_value=["TCS"])) as peers:
        assert (await search.resolve_company_query("reliance"))["peers"] == []
        peers.assert_not_awaited()
        assert (await search.resolve_company_query("reliance", with_peers=True))["peers"] == ["TCS"]
