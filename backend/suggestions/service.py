"""Turning an approved suggestion into a position: on paper, or for an option
proposal the user approves live, a real order with their broker.

The engine's own execution path fills against the bar it is currently
processing; an approval arrives out of band, minutes or hours later, so this
fills against a fresh mark instead. Everything downstream -- costs, the
ledger, the trade lifecycle -- is the same code the runner uses.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.models import Fill, Order, Side
from backend.engine.execution.live_order_store import LiveOrderStore
from backend.instruments.models import Instrument
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.execution.options_costs import calculate_options_costs
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio

logger = logging.getLogger(__name__)

# How long an approve-live request waits for the broker to fill a MARKET
# option order: one status check a second.
LIVE_FILL_CHECKS = 5


async def execute_suggestion(
    suggestion: dict, ledger: LedgerStore, price: float, now: Optional[datetime] = None,
    strategy_name: Optional[str] = None,
) -> Order:
    now = now or datetime.now(timezone.utc)
    side = Side(suggestion["side"])
    is_option = suggestion.get("option_contract") is not None
    product = "NRML" if is_option else ("MIS" if suggestion["mode"] == "INTRADAY" else "CNC")
    quantity = suggestion["quantity"]

    order = Order(
        id=str(uuid.uuid4()), symbol=suggestion["symbol"], side=side, quantity=quantity,
        order_type="MARKET", limit_price=None, product=product,
        strategy_name=strategy_name or suggestion.get("strategy"), suggestion_id=suggestion.get("id"),
    )
    await ledger.record_order(order)

    costs = (
        calculate_options_costs(price, quantity, side) if is_option
        else calculate_indian_costs(price, quantity, side, product)
    )
    fill = Fill(
        order_id=order.id, symbol=order.symbol, side=side, quantity=quantity, price=price,
        timestamp=now, costs=costs,
    )
    await _book(ledger, fill)
    return order


async def _book(ledger: LedgerStore, fill: Fill) -> None:
    portfolio = Portfolio()
    portfolio.positions = await ledger.get_open_positions()
    quantity_before = portfolio.positions[fill.symbol].quantity if fill.symbol in portfolio.positions else 0.0
    portfolio.apply(fill)

    await ledger.on_fill(fill, quantity_before, portfolio.positions[fill.symbol])
    await ledger.snapshot_positions(portfolio.positions)


async def execute_option_suggestion_live(
    suggestion: dict, ledger: LedgerStore, adapter, contract: Instrument, orders: LiveOrderStore,
) -> tuple[Order, str, float]:
    """Places an approved option proposal as a real MARKET order with the
    user's broker, then checks its status for up to LIVE_FILL_CHECKS
    seconds. Whatever filled is booked as a live fill at the broker's own
    average price (charges are the broker's, as for every live fill).
    Returns the order, the broker's last status, and the quantity filled.

    ponytail: an order still working after the checks is left in
    live_orders as pending; the next engine run's status poll would book
    its fill. A dedicated reconciler belongs here if that ever happens."""
    order = Order(
        id=str(uuid.uuid4()), symbol=suggestion["symbol"], side=Side(suggestion["side"]),
        quantity=suggestion["quantity"], order_type="MARKET", limit_price=None, product="NRML",
        contract=contract,
    )
    return await execute_live_order(order, ledger, adapter, orders)


async def execute_live_order(
    order: Order, ledger: LedgerStore, adapter, orders: LiveOrderStore,
    strategy_name: str = "", reason: Optional[str] = None,
) -> tuple[Order, str, float]:
    """Places `order` with the user's broker as a real MARKET order, checks
    its status for up to LIVE_FILL_CHECKS seconds, and books whatever filled
    as a live fill at the broker's own average price. Shared by an option
    proposal approved live and an order confirmed from the chat."""
    broker_order_id = await adapter.place_order(order)
    await ledger.record_order(order)
    await orders.record_submitted(
        order_id=order.id, broker_order_id=broker_order_id, user_id=ledger.user_id,
        strategy_name=strategy_name, symbol=order.symbol, side=order.side, reason=reason,
    )

    status = None
    for check in range(LIVE_FILL_CHECKS):
        try:
            status = await adapter.get_order_status(broker_order_id)
        except Exception as exc:
            logger.warning("approve-live: status of %s failed: %s", broker_order_id, exc)
        if status is not None and status.status in ("FILLED", "REJECTED", "CANCELLED"):
            break
        if check < LIVE_FILL_CHECKS - 1:
            await asyncio.sleep(1)
    if status is None:
        return order, "SUBMITTED", 0.0

    await orders.update_status(order.id, status.status, status.filled_quantity, status.average_price)
    if status.filled_quantity > 0:
        await _book(ledger, Fill(
            order_id=order.id, symbol=order.symbol, side=order.side, quantity=status.filled_quantity,
            price=status.average_price, timestamp=datetime.now(timezone.utc), costs=0.0, venue="live",
        ))
    return order, status.status, status.filled_quantity
