from datetime import datetime, timezone

import pytest

from backend.core.models import Fill, Side
from backend.engine.portfolio import Portfolio

TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _fill(side: Side, qty: float, price: float) -> Fill:
    return Fill(order_id="o1", symbol="TEST", side=side, quantity=qty, price=price, timestamp=TS)


def test_open_add_and_close_realizes_correct_pnl():
    pf = Portfolio()

    pf.apply(_fill(Side.BUY, 10, 100.0))
    pos = pf.positions["TEST"]
    assert pos.quantity == 10
    assert pos.avg_price == 100.0
    assert pos.realized_pnl == 0.0

    pf.apply(_fill(Side.BUY, 5, 110.0))
    pos = pf.positions["TEST"]
    assert pos.quantity == 15
    assert pos.avg_price == pytest.approx((100.0 * 10 + 110.0 * 5) / 15)

    pf.apply(_fill(Side.SELL, 15, 120.0))
    pos = pf.positions["TEST"]
    assert pos.quantity == 0
    assert pos.realized_pnl == pytest.approx(250.0)


def test_partial_close_keeps_remainder_open_at_same_avg_price():
    pf = Portfolio()
    pf.apply(_fill(Side.BUY, 10, 100.0))
    pf.apply(_fill(Side.SELL, 4, 110.0))

    pos = pf.positions["TEST"]
    assert pos.quantity == 6
    assert pos.avg_price == 100.0
    assert pos.realized_pnl == pytest.approx((110.0 - 100.0) * 4)


def test_equity_sums_realized_and_unrealized():
    pf = Portfolio()
    pf.apply(_fill(Side.BUY, 10, 100.0))
    pf.apply(_fill(Side.SELL, 4, 110.0))  # realizes 40.0, leaves 6 open @ 100

    equity = pf.equity({"TEST": 120.0})
    # realized 40.0 + unrealized 6 * (120 - 100) = 120.0 -> 160.0 total
    assert equity == pytest.approx(160.0)
