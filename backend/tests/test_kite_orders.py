"""KiteOrderClient: real pykiteconnect order-API surface, verified against
the installed SDK's place_order/cancel_order/order_history/positions
signatures and Kite Connect v3's public docs. Every SDK call is mocked;
nothing here touches a real account."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.brokers.kite_orders import KiteOrderClient
from backend.core.models import Order, Side


def _order(**overrides) -> Order:
    fields = dict(
        id="app-order-1", symbol="RELIANCE", side=Side.BUY, quantity=10.0,
        order_type="MARKET", product="MIS",
    )
    fields.update(overrides)
    return Order(**fields)


async def test_place_order_maps_fields_and_returns_broker_order_id():
    mock_kite = MagicMock()
    mock_kite.place_order.return_value = "kite-order-1"
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, **kw: fn(**kw))):
        broker_order_id = await client.place_order(_order())

    assert broker_order_id == "kite-order-1"
    call_kwargs = mock_kite.place_order.call_args.kwargs
    assert call_kwargs["tradingsymbol"] == "RELIANCE"
    assert call_kwargs["transaction_type"] == "BUY"
    assert call_kwargs["quantity"] == 10
    assert call_kwargs["product"] == "MIS"
    assert call_kwargs["order_type"] == "MARKET"
    assert call_kwargs["exchange"] == "NSE"
    assert call_kwargs["variety"] == "regular"
    assert call_kwargs["price"] is None  # the SDK drops None params


async def test_limit_order_sends_its_price():
    mock_kite = MagicMock()
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, **kw: fn(**kw))):
        await client.place_order(_order(order_type="LIMIT", limit_price=1490.5))

    call_kwargs = mock_kite.place_order.call_args.kwargs
    assert (call_kwargs["order_type"], call_kwargs["price"]) == ("LIMIT", 1490.5)


async def test_cancel_order_calls_sdk_with_regular_variety():
    mock_kite = MagicMock()
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, **kw: fn(**kw))):
        await client.cancel_order("kite-order-1")

    mock_kite.cancel_order.assert_called_once_with(variety="regular", order_id="kite-order-1")


async def test_get_order_status_maps_complete_to_filled():
    mock_kite = MagicMock()
    mock_kite.order_history.return_value = [
        {"status": "OPEN", "filled_quantity": 0, "average_price": 0.0},
        {"status": "COMPLETE", "filled_quantity": 10, "average_price": 2500.5},
    ]
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        status = await client.get_order_status("kite-order-1")

    assert status.status == "FILLED"
    assert status.filled_quantity == 10
    assert status.average_price == 2500.5
    assert status.broker_order_id == "kite-order-1"


async def test_get_order_status_maps_rejected():
    mock_kite = MagicMock()
    mock_kite.order_history.return_value = [
        {"status": "REJECTED", "filled_quantity": 0, "average_price": 0.0},
    ]
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        status = await client.get_order_status("kite-order-1")

    assert status.status == "REJECTED"


async def test_get_order_status_maps_partial_fill():
    mock_kite = MagicMock()
    mock_kite.order_history.return_value = [
        {"status": "OPEN", "filled_quantity": 4, "average_price": 2500.0},
    ]
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a: fn(*a))):
        status = await client.get_order_status("kite-order-1")

    assert status.status == "PARTIALLY_FILLED"


async def test_get_positions_maps_net_positions():
    mock_kite = MagicMock()
    mock_kite.positions.return_value = {
        "net": [{"tradingsymbol": "RELIANCE", "quantity": 10, "average_price": 2500.0,
                  "realised": 0.0, "unrealised": 150.0}],
        "day": [],
    }
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        positions = await client.get_positions()

    assert positions["RELIANCE"].quantity == 10
    assert positions["RELIANCE"].avg_price == 2500.0
    assert positions["RELIANCE"].unrealized_pnl == 150.0


async def test_get_positions_keeps_mis_and_cnc_of_one_symbol_apart():
    """Kite lists one row per product: keyed by symbol alone, the CNC row
    overwrote the MIS one and the 3:15 square-off never saw it."""
    mock_kite = MagicMock()
    mock_kite.positions.return_value = {"net": [
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "quantity": 10, "average_price": 2500.0},
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC", "quantity": 5, "average_price": 2400.0},
    ], "day": []}
    client = KiteOrderClient(kite_client_factory=lambda: mock_kite)

    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        positions = await client.get_positions()

    assert sorted((p.symbol, p.product, p.quantity) for p in positions.values()) == [
        ("RELIANCE", "CNC", 5), ("RELIANCE", "MIS", 10)]
    assert positions["RELIANCE"].product == "MIS"  # the first row keeps the plain symbol key

