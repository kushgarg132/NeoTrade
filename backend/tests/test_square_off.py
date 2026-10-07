"""Guardrail square-off: which positions it closes, that preview never
places an order, that live places each exit once per day, and that the
adapters report the product/exchange it depends on."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from mongomock_motor import AsyncMongoMockClient

from backend.brokers.kite_orders import KiteOrderClient
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.trades import parse_ist
from backend.brokers.upstox import UpstoxAdapter
from backend.core.models import Position, Side
from backend.guardrails import monitor
from backend.guardrails.square_off import describe, exit_orders


def _pos(symbol, qty, exchange="NSE", product="MIS"):
    return Position(symbol=symbol, quantity=qty, exchange=exchange, product=product)


def test_only_nse_intraday_positions_are_closed_in_the_right_direction():
    orders, left = exit_orders({
        "SBIN": _pos("SBIN", 100),
        "INFY": _pos("INFY", -20),
        "TCS": _pos("TCS", 5, product="CNC"),
        "NIFTY24SEPFUT": _pos("NIFTY24SEPFUT", 50, exchange="NFO", product="NRML"),
        "HDFC": _pos("HDFC", 3, exchange=None, product=None),
        "FLAT": _pos("FLAT", 0),
    })
    assert [(o.symbol, o.side, o.quantity, o.product, o.order_type) for o in orders] == [
        ("SBIN", Side.SELL, 100, "MIS", "MARKET"),
        ("INFY", Side.BUY, 20, "MIS", "MARKET"),
    ]
    assert describe(orders) == "sell 100 SBIN, buy 20 INFY"
    assert left == [
        "TCS (CNC on NSE)",
        "NIFTY24SEPFUT (NRML on NFO)",
        "HDFC (unknown product on unknown exchange)",
    ]


def _adapter(positions, place=None):
    adapter = MagicMock()
    adapter.state = AsyncMock(return_value=BrokerSessionState.ACTIVE)
    adapter.get_positions = AsyncMock(return_value=positions)
    adapter.place_order = place or AsyncMock(return_value="broker-1")
    return adapter


def _patch_brokers(monkeypatch, adapter):
    monkeypatch.setattr(monitor, "BROKERS", {"kite": None})
    monkeypatch.setattr(monitor, "get_broker_adapter", AsyncMock(return_value=adapter))


async def test_preview_never_places_an_order(monkeypatch):
    adapter = _adapter({"SBIN": _pos("SBIN", 100), "TCS": _pos("TCS", 5, product="CNC")})
    _patch_brokers(monkeypatch, adapter)
    [alert] = await monitor.square_off(None, None, {"user_id": "alice", "auto_square_off": "preview"})
    adapter.place_order.assert_not_awaited()
    assert alert["title"] == "kite: square-off preview"
    assert "Would place: sell 100 SBIN" in alert["detail"]
    assert "Not touched: TCS (CNC on NSE)" in alert["detail"]


async def test_live_places_and_reports_failures(monkeypatch):
    place = AsyncMock(side_effect=["ok", RuntimeError("rejected")])
    adapter = _adapter({"SBIN": _pos("SBIN", 100), "INFY": _pos("INFY", -20)}, place=place)
    _patch_brokers(monkeypatch, adapter)
    [alert] = await monitor.square_off(None, None, {"user_id": "alice", "auto_square_off": "live"})
    assert place.await_count == 2
    assert alert["title"] == "kite: square-off sent"
    assert "Sent: sell 100 SBIN." in alert["detail"]
    assert "Failed, close these yourself: buy 20 INFY." in alert["detail"]


async def test_unreadable_positions_tell_the_user_to_close_manually(monkeypatch):
    adapter = _adapter({})
    adapter.get_positions = AsyncMock(side_effect=RuntimeError("timeout"))
    _patch_brokers(monkeypatch, adapter)
    [alert] = await monitor.square_off(None, None, {"user_id": "alice", "auto_square_off": "live"})
    adapter.place_order.assert_not_awaited()
    assert "Close your intraday positions yourself" in alert["detail"]


async def _run_check(monkeypatch, mode, adapter):
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(monitor, "sync_user_trades", AsyncMock(return_value={
        "imported": 0, "brokers": ["kite"], "failed": [], "day_pnl": -20_000.0}))
    monkeypatch.setattr(monitor.hub, "publish", AsyncMock())
    _patch_brokers(monkeypatch, adapter)
    prefs = {"user_id": "alice", "daily_loss_limit": 10_000, "auto_square_off": mode}
    now = parse_ist(datetime(2026, 9, 1, 11, 0))
    await monitor.check_user(db, None, None, prefs, now)
    await monitor.check_user(db, None, None, prefs, now)  # next minute, same breach
    return db


async def test_live_square_off_runs_once_per_day(monkeypatch):
    adapter = _adapter({"SBIN": _pos("SBIN", 100)})
    db = await _run_check(monkeypatch, "live", adapter)
    adapter.place_order.assert_awaited_once()
    rules = [e["rule"] async for e in db["guardrail_events"].find({})]
    assert sorted(rules) == ["daily_loss", "square_off"]


async def test_off_does_not_touch_positions(monkeypatch):
    adapter = _adapter({"SBIN": _pos("SBIN", 100)})
    await _run_check(monkeypatch, "off", adapter)
    adapter.get_positions.assert_not_awaited()
    adapter.place_order.assert_not_awaited()


async def test_kite_positions_carry_exchange_and_product():
    kite = MagicMock()
    kite.positions.return_value = {"net": [{
        "tradingsymbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": 10,
        "average_price": 800.0, "realised": 0.0, "unrealised": -50.0,
    }], "day": []}
    client = KiteOrderClient(kite_client_factory=lambda: kite)
    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        positions = await client.get_positions()
    assert (positions["SBIN"].exchange, positions["SBIN"].product) == ("NSE", "MIS")


async def test_upstox_positions_map_product_codes(monkeypatch):
    redis = MagicMock()
    redis.get = AsyncMock(return_value="tok")
    adapter = UpstoxAdapter(api_key="k", api_secret="s", redirect_uri="https://x/cb", redis=redis, user_id="alice")

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"data": [
            {"trading_symbol": "SBIN", "exchange": "NSE", "product": "I", "quantity": 10, "average_price": 800},
            {"trading_symbol": "TCS", "exchange": "NSE", "product": "D", "quantity": 1, "average_price": 4000},
            {"trading_symbol": "NIFTYFUT", "exchange": "NFO", "product": "D", "quantity": 50, "average_price": 1},
        ]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    positions = await adapter.get_positions()
    assert (positions["SBIN"].exchange, positions["SBIN"].product) == ("NSE", "MIS")
    assert positions["TCS"].product == "CNC"
    assert positions["NIFTYFUT"].exchange == "NFO"


async def test_square_off_never_touches_the_ai_account(monkeypatch):
    # Guardrails are the user's own rules: the AI account is the autopilot's.
    adapter = _adapter({"SBIN": _pos("SBIN", 100)})
    _patch_brokers(monkeypatch, adapter)
    prefs = {"user_id": "alice", "auto_square_off": "live", "broker_roles": {"kite": "ai"}}
    assert await monitor.square_off(None, None, prefs) == []
    adapter.get_positions.assert_not_awaited()
    adapter.place_order.assert_not_awaited()
