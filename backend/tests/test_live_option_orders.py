"""Live options orders: Kite and Upstox place NFO orders for a contract,
Angel One refuses, and routing sends an option order live only through a
broker that supports it. Every broker call is mocked."""

import gzip
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.brokers.angel_one import AngelOneAdapter
from backend.brokers.kite_orders import KiteOrderClient
from backend.core.models import Order, Side
from backend.engine.execution.routing import RoutingExecutionClient
from backend.engine.execution.simulated import SimulatedExecutionClient
from backend.instruments.models import Instrument
from backend.tests.test_upstox_adapter import _adapter, _redis, _scrip

CONTRACT = Instrument(
    exchange="NFO", tradingsymbol="RELIANCE24DEC1300CE", name="RELIANCE", instrument_token=11,
    exchange_token=11, instrument_type="CE", segment="NFO-OPT", lot_size=500, tick_size=0.05,
    expiry=datetime(2024, 12, 26), strike=1300.0,
)


def _order(**overrides):
    fields = dict(id="o1", symbol=CONTRACT.tradingsymbol, side=Side.BUY, quantity=500.0,
                  order_type="MARKET", product="MIS", contract=CONTRACT, strategy_name="orb_options")
    return Order(**{**fields, **overrides})


async def test_kite_places_an_option_order_on_nfo():
    kite = MagicMock()
    kite.place_order.return_value = "k1"
    with patch("backend.brokers.kite_orders.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, **kw: fn(**kw))):
        assert await KiteOrderClient(lambda: kite).place_order(_order(product="NRML")) == "k1"
    kwargs = kite.place_order.call_args.kwargs
    assert (kwargs["exchange"], kwargs["tradingsymbol"], kwargs["quantity"], kwargs["product"]) == (
        "NFO", "RELIANCE24DEC1300CE", 500, "NRML",
    )


async def test_upstox_finds_the_contracts_instrument_key_on_the_option_chain(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)
    captured = {}

    async def fake_get(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url)
        if "option/chain" in url:
            captured["chain_params"] = params
            leg = lambda key: {"instrument_key": key, "market_data": {"ltp": 12.0}}  # noqa: E731
            return httpx.Response(200, request=request, json={"data": [
                {"strike_price": 1280.0, "call_options": leg("NSE_FO|1"), "put_options": leg("NSE_FO|2")},
                {"strike_price": 1300.0, "call_options": leg("NSE_FO|3"), "put_options": leg("NSE_FO|4")},
            ]})
        return httpx.Response(200, request=request, content=gzip.compress(json.dumps(_scrip()).encode()))

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url), json={"data": {"order_id": "u1"}})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    assert await adapter.place_order(_order(product="NRML")) == "u1"
    assert captured["chain_params"] == {"instrument_key": "NSE_EQ|INE002A01018", "expiry_date": "2024-12-26"}
    assert captured["json"]["instrument_token"] == "NSE_FO|3"
    assert (captured["json"]["quantity"], captured["json"]["product"]) == (500, "D")


async def test_upstox_refuses_a_contract_missing_from_its_chain(monkeypatch):
    redis = _redis()
    await redis.set("broker:alice:upstox:access_token", "up-tok")
    adapter = _adapter(redis)

    async def fake_get(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url)
        if "option/chain" in url:
            return httpx.Response(200, request=request, json={"data": []})
        return httpx.Response(200, request=request, content=gzip.compress(json.dumps(_scrip()).encode()))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", AsyncMock(side_effect=AssertionError("order placed")))
    with pytest.raises(ValueError, match="not found on Upstox's option chain"):
        await adapter.place_order(_order())


async def test_angel_one_refuses_option_orders():
    adapter = AngelOneAdapter(api_key="k", api_secret=None, redis=_redis(), user_id="alice")
    assert adapter.supports_options is False
    with pytest.raises(ValueError, match="not supported"):
        await adapter.place_order(_order())


class _Live:
    def __init__(self, supports_options):
        self.supports_options = supports_options
        self.placed = []

    async def submit(self, order):
        self.placed.append(order)
        return order.id


@pytest.mark.parametrize("supports, goes_live", [(True, True), (False, False)])
async def test_routing_sends_option_orders_live_only_through_a_broker_that_places_them(supports, goes_live):
    paper, live = SimulatedExecutionClient(), _Live(supports)
    paper.mark(CONTRACT.tradingsymbol, 12.0, datetime(2024, 12, 2))
    routing = RoutingExecutionClient(paper=paper, live_by_strategy={"orb_options": live})
    await routing.submit(_order())
    assert bool(live.placed) is goes_live
