"""Paper and live engine records are two books that must never mix: the
Paper tab reads venue=paper, the real-money statement venue=live.

Rows written before venues existed carry no tag and were all paper, so the
paper book includes them and the live book never does.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.analytics import compute_pnl
from backend.core.models import Fill, Position, Side
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio

T0 = datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc)  # 09:30 IST


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def ledger(mongo):
    return LedgerStore(mongo, user_id="alice", run_id="run-1")


def _fill(symbol: str, side: Side, price: float, venue: str = "paper", minutes: int = 0) -> Fill:
    return Fill(
        order_id=f"{symbol}-{side.value}-{minutes}", symbol=symbol, side=side, quantity=10.0,
        price=price, timestamp=T0 + timedelta(minutes=minutes), costs=0.0, venue=venue,
    )


async def _round_trip(ledger, symbol: str, venue: str, entry: float, exit: float) -> None:
    portfolio = Portfolio()
    for fill in (_fill(symbol, Side.BUY, entry, venue), _fill(symbol, Side.SELL, exit, venue, minutes=5)):
        before = portfolio.positions[symbol].quantity if symbol in portfolio.positions else 0.0
        portfolio.apply(fill)
        await ledger.on_fill(fill, before, portfolio.positions[symbol])


def test_fills_default_to_paper():
    fill = Fill(order_id="o", symbol="X", side=Side.BUY, quantity=1, price=1, timestamp=T0)
    assert fill.venue == "paper"


def test_a_position_takes_the_venue_of_the_fill_that_opened_it():
    portfolio = Portfolio()
    portfolio.apply(_fill("RELIANCE", Side.BUY, 100.0, venue="live"))
    assert portfolio.positions["RELIANCE"].venue == "live"


@pytest.mark.asyncio
async def test_a_trade_keeps_its_opening_venue_through_the_close(ledger):
    await _round_trip(ledger, "RELIANCE", "live", 100.0, 110.0)

    (trade,) = await ledger.get_trades()
    assert trade["status"] == "CLOSED"
    assert trade["venue"] == "live"


@pytest.mark.asyncio
async def test_trades_split_by_venue(ledger):
    await _round_trip(ledger, "RELIANCE", "live", 100.0, 110.0)
    await _round_trip(ledger, "TCS", "paper", 100.0, 90.0)

    assert [t["symbol"] for t in await ledger.get_trades(venue="live")] == ["RELIANCE"]
    assert [t["symbol"] for t in await ledger.get_trades(venue="paper")] == ["TCS"]
    assert len(await ledger.get_trades()) == 2


@pytest.mark.asyncio
async def test_untagged_legacy_rows_read_as_paper_never_live(ledger, mongo):
    await mongo["paper_trades"].insert_one({
        "user_id": "alice", "id": "old", "symbol": "INFY", "status": "OPEN", "entry_at": T0,
    })
    await mongo["paper_positions"].insert_one({
        "user_id": "alice", "symbol": "INFY", "quantity": 5.0, "avg_price": 100.0,
    })
    await mongo["paper_fills"].insert_one({
        "user_id": "alice", "order_id": "old", "symbol": "INFY", "side": "BUY",
        "quantity": 5.0, "price": 100.0, "timestamp": T0,
    })

    assert [t["id"] for t in await ledger.get_trades(venue="paper")] == ["old"]
    assert await ledger.get_trades(venue="live") == []
    assert list(await ledger.get_open_positions(venue="paper")) == ["INFY"]
    assert await ledger.get_open_positions(venue="live") == {}
    assert [f.venue for f in await ledger.get_fills(venue="paper")] == ["paper"]
    assert await ledger.get_fills(venue="live") == []


@pytest.mark.asyncio
async def test_fills_and_positions_split_by_venue(ledger):
    await ledger.record_fill(_fill("RELIANCE", Side.BUY, 100.0, venue="live"))
    await ledger.record_fill(_fill("TCS", Side.BUY, 100.0, venue="paper"))
    await ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0, venue="live"),
        "TCS": Position(symbol="TCS", quantity=10.0, avg_price=100.0, venue="paper"),
    })

    assert [f.symbol for f in await ledger.get_fills(venue="live")] == ["RELIANCE"]
    assert [f.symbol for f in await ledger.get_fills(venue="paper")] == ["TCS"]
    assert list(await ledger.get_open_positions(venue="live")) == ["RELIANCE"]
    assert list(await ledger.get_open_positions(venue="paper")) == ["TCS"]


@pytest.mark.asyncio
async def test_pnl_for_one_venue_ignores_the_other(ledger):
    await _round_trip(ledger, "RELIANCE", "live", 100.0, 110.0)  # +100
    await _round_trip(ledger, "TCS", "paper", 100.0, 90.0)  # -100
    now = T0 + timedelta(hours=1)

    live = await compute_pnl(ledger, {}, now=now, venue="live")
    paper = await compute_pnl(ledger, {}, now=now, venue="paper")
    both = await compute_pnl(ledger, {}, now=now)

    assert live["today"]["realized"] == pytest.approx(100.0)
    assert live["today"]["trades"] == 1
    assert paper["today"]["realized"] == pytest.approx(-100.0)
    assert both["today"]["realized"] == pytest.approx(0.0)
    assert both["today"]["trades"] == 2
