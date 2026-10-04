"""Cards the AI may propose on the user's own account (role "mine",
backend/brokers/roles.py): exit a holding, cancel or modify an open order,
add a stop-loss. Each is propose-only -- the user confirms (twice: real
money) -- and confirm re-checks the account, because a holding or an order
can change between the card and the tap. Exits, cancels and stops reduce
risk, so the daily kill switch does not block them; the market must be open."""

import uuid
from typing import Optional

from backend.core.models import Order, Side


class _Refused(Exception):
    pass


async def mine_adapter(user_id: str, credentials):
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.roles import RoleUnavailable, adapter_for
    from backend.chat.actions import ActionRefused

    try:
        return await adapter_for(user_id, "mine", credentials or get_credential_store())
    except RoleUnavailable as exc:
        raise ActionRefused(exc.reason)


async def _held(adapter, symbol: str) -> tuple[int, str]:
    """(shares held, product) -- an intraday position first, else a holding."""
    position = (await adapter.get_positions()).get(symbol)
    if position is not None and position.quantity > 0:
        return int(position.quantity), "MIS"
    held = sum(h.quantity for h in await adapter.get_holdings() if h.symbol == symbol)
    return int(held), "CNC"


async def _open_order(adapter, order_id: str) -> Optional[dict]:
    closed = {"complete", "cancelled", "rejected"}
    return next((o for o in await adapter.get_orders()
                 if o["order_id"] == order_id and str(o.get("status", "")).lower() not in closed), None)


async def propose_exit(adapter, symbol: str, quantity: Optional[int]) -> tuple:
    symbol = symbol.strip().upper().removesuffix(".NS")
    held, product = await _held(adapter, symbol)
    if held <= 0:
        raise _Refused(f"You don't hold {symbol} in your account.")
    quantity = quantity or held
    if quantity <= 0 or quantity > held:
        raise _Refused(f"You hold {held} {symbol}; choose 1 to {held}.")
    return "exit", {"symbol": symbol, "quantity": quantity, "product": product}, \
        f"Sell {quantity} {symbol} in your account (market order)"


async def propose_cancel(adapter, order_id: str) -> tuple:
    order = await _open_order(adapter, order_id)
    if order is None:
        raise _Refused(f"There is no open order {order_id} in your account.")
    return "cancel_order", {"order_id": order_id}, \
        f"Cancel order {order_id}: {order['side']} {order['quantity']:g} {order['symbol']}"


async def propose_modify(adapter, order_id: str, price: Optional[float], quantity: Optional[int]) -> tuple:
    if price is None and quantity is None:
        raise _Refused("Say the new price or quantity.")
    order = await _open_order(adapter, order_id)
    if order is None:
        raise _Refused(f"There is no open order {order_id} in your account.")
    change = ", ".join(filter(None, [f"price ₹{price:,.2f}" if price else "", f"quantity {quantity}" if quantity else ""]))
    return "modify_order", {"order_id": order_id, "price": price, "quantity": quantity}, \
        f"Change order {order_id} ({order['side']} {order['symbol']}): {change}"


async def propose_stop(adapter, symbol: str, trigger_price: float, last_price: float) -> tuple:
    symbol = symbol.strip().upper().removesuffix(".NS")
    held, product = await _held(adapter, symbol)
    if held <= 0:
        raise _Refused(f"You don't hold {symbol} in your account.")
    if trigger_price >= last_price:
        raise _Refused(f"A stop-loss trigger must be below the price (₹{last_price:,.2f}).")
    return "stop_loss", {"symbol": symbol, "quantity": held, "trigger_price": trigger_price, "product": product}, \
        f"Stop-loss on {held} {symbol} in your account at ₹{trigger_price:,.2f} (SL-M)"


async def execute(adapter, kind: str, params: dict) -> str:
    """Confirm: re-check against the account, then act on it."""
    if kind == "exit":
        held, product = await _held(adapter, params["symbol"])
        if held < params["quantity"]:
            raise _Refused(f"You now hold {held} {params['symbol']}, fewer than the card's {params['quantity']}.")
        broker_id = await adapter.place_order(Order(
            id=str(uuid.uuid4()), symbol=params["symbol"], side=Side.SELL, quantity=params["quantity"],
            order_type="MARKET", product=product, strategy_name="chat"))
        return f"Sell order sent to your account ({broker_id})."
    if kind == "stop_loss":
        held, product = await _held(adapter, params["symbol"])
        if held <= 0:
            raise _Refused(f"You no longer hold {params['symbol']}.")
        broker_id = await adapter.place_order(Order(
            id=str(uuid.uuid4()), symbol=params["symbol"], side=Side.SELL, quantity=min(held, params["quantity"]),
            order_type="SL-M", trigger_price=params["trigger_price"], product=product, strategy_name="chat"))
        return f"Stop-loss placed in your account ({broker_id})."
    if await _open_order(adapter, params["order_id"]) is None:
        raise _Refused(f"Order {params['order_id']} is no longer open.")
    if kind == "cancel_order":
        await adapter.cancel_order(params["order_id"])
        return f"Order {params['order_id']} cancelled."
    if not hasattr(adapter, "modify_order"):
        raise _Refused("Your broker does not support changing orders from here yet.")
    await adapter.modify_order(params["order_id"], quantity=params.get("quantity"), price=params.get("price"))
    return f"Order {params['order_id']} changed."
