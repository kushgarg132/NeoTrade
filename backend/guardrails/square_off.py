"""Exit orders for a user's open broker positions once their daily loss
limit is hit. Pure: turns a position book into MARKET orders, plus a list of
what it will not touch and why.

Only NSE intraday (MIS) positions are closed. Every adapter's place_order is
NSE-cash-only today, and closing a delivery (CNC) or F&O (NRML) position is
a decision about more than today's session -- those are left to the user
and named in the alert.
"""

import uuid

from backend.core.models import Order, Position, Side


def exit_orders(positions: dict[str, Position]) -> tuple[list[Order], list[str]]:
    orders, left = [], []
    for position in positions.values():
        qty = position.quantity
        if abs(qty) < 1e-9:
            continue
        if position.exchange != "NSE" or position.product != "MIS":
            left.append(f"{position.symbol} ({position.product or 'unknown product'} on "
                        f"{position.exchange or 'unknown exchange'})")
            continue
        if qty != int(qty):
            left.append(f"{position.symbol} (fractional quantity {qty})")
            continue
        orders.append(Order(
            id=str(uuid.uuid4()), symbol=position.symbol,
            side=Side.SELL if qty > 0 else Side.BUY, quantity=abs(int(qty)),
            order_type="MARKET", product="MIS",
        ))
    return orders, left


def describe(orders: list[Order]) -> str:
    return ", ".join(f"{o.side.value.lower()} {int(o.quantity)} {o.symbol}" for o in orders)
