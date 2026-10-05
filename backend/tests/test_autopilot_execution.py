"""An engine strategy switched live trades the AI account only through the
autopilot: its fence (capital, per-trade cap, trades/day, Nifty 200, no
shorts) applies and the fill books to the AI ledger. Before, live engine
orders went straight to the AI broker past the fence (AGENTS.md: only
backend/autopilot/ may place AI-account orders)."""

import pytest

from backend.core.models import Order, Side
from backend.engine.execution.autopilot import AutopilotExecutionClient


@pytest.mark.asyncio
async def test_a_live_engine_order_goes_through_the_autopilot(monkeypatch):
    from backend.autopilot import service

    sent = []

    async def submit(db, redis, user_id, order, now=None, suggestion_id=None, quiet=False):
        sent.append((user_id, order))
        return {"status": "FILLED", "price": 101.0}

    monkeypatch.setattr(service, "submit", submit)
    client = AutopilotExecutionClient(db=object(), redis=None, user_id="alice")
    await client.submit(Order(id="o1", symbol="ITC", side=Side.BUY, quantity=12.0, order_type="MARKET",
                              product="MIS", strategy_name="vwap_reversion"))

    ((user, order),) = sent
    assert (user, order.symbol, order.side, order.quantity, order.product, order.source) == \
        ("alice", "ITC", Side.BUY, 12, "MIS", "engine")
    assert "vwap_reversion" in order.reason
    # The autopilot books the fill to the AI ledger; the engine's own (paper)
    # ledger must not book it a second time.
    assert [f async for f in client.fills()] == []
