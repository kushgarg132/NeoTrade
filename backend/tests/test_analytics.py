"""P&L analytics -- what the dashboard cards read.

Day and month boundaries are IST, not UTC: a trade closed at 15:20 IST is
today's trade, and computing it in UTC would file it under yesterday for
anyone looking before 05:30 IST the next morning.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.analytics import compute_pnl
from backend.core.models import Position, Side
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST

# 2024-01-15 11:00 IST, a Monday mid-session.
NOW = datetime(2024, 1, 15, 11, 0, tzinfo=IST)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def ledger(mongo):
    return LedgerStore(mongo, user_id="alice")


async def _closed_trade(ledger, realized: float, exit_at: datetime, quantity: float = 10.0,
                        entry_price: float = 100.0, symbol: str = "RELIANCE", costs=10.0) -> None:
    await ledger.trades.insert_one({
        "id": f"t-{exit_at.isoformat()}-{symbol}", "user_id": "alice", "run_id": None,
        "symbol": symbol, "mode": "LONGTERM", "side": Side.BUY.value, "status": "CLOSED",
        "quantity": quantity, "entry_price": entry_price, "entry_at": exit_at - timedelta(hours=2),
        "exit_price": entry_price + realized / quantity, "exit_at": exit_at,
        "realized_pnl": realized, "suggestion_id": None,
        **({} if costs is None else {"costs": costs}),
    })


@pytest.mark.asyncio
async def test_today_counts_only_todays_closed_trades(ledger):
    await _closed_trade(ledger, realized=500.0, exit_at=NOW - timedelta(hours=1))
    await _closed_trade(ledger, realized=-200.0, exit_at=NOW - timedelta(hours=2), symbol="TCS")
    await _closed_trade(ledger, realized=9999.0, exit_at=NOW - timedelta(days=3), symbol="INFY")

    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)

    assert pnl["today"]["realized"] == 300.0
    assert pnl["today"]["trades"] == 2
    assert pnl["today"]["wins"] == 1
    assert pnl["today"]["losses"] == 1


@pytest.mark.asyncio
async def test_a_trade_closed_late_in_the_ist_day_still_counts_as_today(ledger):
    """15:20 IST is 09:50 UTC -- a UTC-based day boundary gets this right by
    luck here, but 23:00 IST (17:30 UTC the previous day) is where naive UTC
    truncation silently drops a trade from today's card."""
    late_ist = NOW.replace(hour=23, minute=0)
    await _closed_trade(ledger, realized=750.0, exit_at=late_ist)

    pnl = await compute_pnl(ledger, mark_prices={}, now=late_ist + timedelta(minutes=30))

    assert pnl["today"]["realized"] == 750.0


@pytest.mark.asyncio
async def test_month_aggregates_the_calendar_month_with_a_win_rate(ledger):
    await _closed_trade(ledger, realized=500.0, exit_at=NOW - timedelta(days=1))
    await _closed_trade(ledger, realized=300.0, exit_at=NOW - timedelta(days=5), symbol="TCS")
    await _closed_trade(ledger, realized=-100.0, exit_at=NOW - timedelta(days=10), symbol="INFY")
    await _closed_trade(ledger, realized=4000.0, exit_at=NOW - timedelta(days=40), symbol="WIPRO")

    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)

    assert pnl["month"]["realized"] == 700.0
    assert pnl["month"]["trades"] == 3
    assert pnl["month"]["win_rate"] == pytest.approx(2 / 3)
    assert pnl["month"]["best"] == 500.0
    assert pnl["month"]["worst"] == -100.0


@pytest.mark.asyncio
async def test_open_section_marks_positions_to_market(ledger):
    await ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0),
        "TCS": Position(symbol="TCS", quantity=5.0, avg_price=200.0),
    })

    pnl = await compute_pnl(ledger, mark_prices={"RELIANCE": 110.0, "TCS": 180.0}, now=NOW)

    assert pnl["open"]["positions"] == 2
    assert pnl["open"]["exposure"] == pytest.approx(10 * 100.0 + 5 * 200.0)
    assert pnl["today"]["unrealized"] == pytest.approx(10 * 10.0 + 5 * -20.0)  # +100 -100


@pytest.mark.asyncio
async def test_a_symbol_with_no_mark_contributes_no_unrealized_pnl(ledger):
    """Missing quote must not be read as a 100% loss."""
    await ledger.snapshot_positions({"RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0)})

    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)

    assert pnl["today"]["unrealized"] == 0.0


@pytest.mark.asyncio
async def test_an_empty_book_reports_zeroes_not_errors(ledger):
    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)

    assert pnl["today"] == {"realized": 0.0, "unrealized": 0.0, "trades": 0, "wins": 0,
                            "losses": 0, "turnover": 0.0}
    assert pnl["month"]["win_rate"] == 0.0
    assert pnl["open"]["equity"] == 0.0


@pytest.mark.asyncio
async def test_analytics_are_scoped_to_the_caller(mongo):
    alice = LedgerStore(mongo, user_id="alice")
    bob = LedgerStore(mongo, user_id="bob")
    await _closed_trade(alice, realized=500.0, exit_at=NOW - timedelta(hours=1))

    assert (await compute_pnl(bob, mark_prices={}, now=NOW))["today"]["realized"] == 0.0


@pytest.mark.asyncio
async def test_mode_splits_the_book_into_intraday_and_long_term(ledger):
    from backend.analytics import compute_scorecard

    await _closed_trade(ledger, realized=500.0, exit_at=NOW - timedelta(hours=1))  # LONGTERM
    await ledger.trades.insert_one({
        "id": "t-intra", "user_id": "alice", "symbol": "TCS", "mode": "INTRADAY", "side": "BUY",
        "status": "CLOSED", "quantity": 10.0, "entry_price": 100.0, "entry_at": NOW - timedelta(hours=1),
        "exit_price": 98.0, "exit_at": NOW - timedelta(minutes=30), "realized_pnl": -20.0, "costs": 1.0,
    })
    await ledger.trades.insert_one({
        "id": "t-hold", "user_id": "alice", "symbol": "SJVN", "mode": "LONGTERM", "side": "BUY",
        "status": "OPEN", "quantity": 100.0, "entry_price": 50.0, "entry_at": NOW - timedelta(days=5),
        "exit_price": None, "exit_at": None, "realized_pnl": 0.0, "costs": 2.0,
    })
    marks = {"SJVN": 55.0}

    longterm = await compute_pnl(ledger, marks, now=NOW, mode="LONGTERM")
    intraday = await compute_pnl(ledger, marks, now=NOW, mode="INTRADAY")
    assert (longterm["today"]["realized"], longterm["today"]["trades"]) == (500.0, 1)
    assert longterm["open"] == {"positions": 1, "exposure": 5000.0, "equity": 500.0}
    assert longterm["today"]["unrealized"] == 500.0
    assert (intraday["today"]["realized"], intraday["open"]["positions"]) == (-20.0, 0)

    card = await compute_scorecard(ledger, "paper", 1_000_000, mode="INTRADAY")
    assert card["totals"]["trades"] == 1 and card["totals"]["net"] == -21.0


@pytest.mark.asyncio
async def test_net_subtracts_charges_per_period(ledger):
    await _closed_trade(ledger, realized=100.0, exit_at=NOW - timedelta(hours=1), costs=5.0)
    await _closed_trade(ledger, realized=-20.0, exit_at=NOW - timedelta(hours=2), symbol="TCS", costs=3.0)

    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)

    assert pnl["today"]["costs"] == 8.0 and pnl["today"]["net"] == 72.0
    assert pnl["month"]["net"] == 72.0
    assert pnl["all_time"] == {"realized": 80.0, "costs": 8.0, "net": 72.0, "trades": 2, "wins": 1}


@pytest.mark.asyncio
async def test_missing_costs_count_as_zero(ledger):
    await _closed_trade(ledger, realized=50.0, exit_at=NOW - timedelta(hours=1), costs=None)
    pnl = await compute_pnl(ledger, mark_prices={}, now=NOW)
    assert pnl["today"]["net"] == 50.0 and pnl["all_time"]["net"] == 50.0
