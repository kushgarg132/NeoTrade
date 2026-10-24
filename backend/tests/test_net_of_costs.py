"""Phase 23.0 task 3: loss limits, win/loss counts and the kill switch read P&L net of costs."""
import inspect
from datetime import datetime, timezone

import pytest

from backend.analytics import compute_pnl
from backend.core.models import Fill, Side
from backend.engine.persistence import trade_net
from backend.engine.portfolio import Portfolio

T = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)


def _fill(side, price, costs):
    return Fill(order_id="o", symbol="ITC", side=side, quantity=10, price=price, timestamp=T, costs=costs)


def test_equity_is_net_of_costs_so_the_kill_switch_trips_on_net_loss():
    p = Portfolio()
    p.apply(_fill(Side.BUY, 100.0, 30.0))
    p.apply(_fill(Side.SELL, 101.0, 30.0))  # gross +10, net -50
    assert p.positions["ITC"].realized_pnl == 10.0
    assert p.equity({}) == -50.0


def test_trade_net_falls_back_to_gross_minus_costs_for_old_rows():
    assert trade_net({"realized_pnl": 10.0, "costs": 25.0}) == -15.0
    assert trade_net({"realized_pnl": 10.0, "costs": 25.0, "net_pnl": 3.0}) == 3.0


class _Ledger:
    async def get_trades(self, **kw):
        if kw.get("status") == "OPEN":
            return []
        return [{"realized_pnl": 10.0, "costs": 25.0, "exit_at": T, "entry_at": T, "quantity": 1, "entry_price": 1}]

    async def get_open_positions(self, **kw):
        return {}


@pytest.mark.asyncio
async def test_gross_positive_net_negative_trade_counts_as_a_loss():
    out = await compute_pnl(_Ledger(), {}, now=T)
    assert (out["today"]["wins"], out["today"]["losses"]) == (0, 1)
    assert out["month"]["win_rate"] == 0.0


def test_paper_intraday_fills_on_next_open():
    from backend.routers import trading
    assert "fill_on_next_open=True" in inspect.getsource(trading)
