"""Cards the AI can propose on the user's own account: exit, cancel, modify,
stop-loss. Nothing reaches the broker until the user confirms, the account
must still hold what the card is about, and only the user's account is used."""

import json
from datetime import datetime

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.chat import account_actions, actions
from backend.chat.actions import ActionRefused, action_tools, confirm
from backend.core.models import Holding, Position, Side
from backend.engine.session import IST

OPEN = datetime(2026, 10, 6, 11, 0, tzinfo=IST)  # a Tuesday, in session


class _Broker:
    def __init__(self, name="upstox"):
        self.name, self.calls = name, []
        self.holdings = [Holding(symbol="INFY", quantity=10, avg_price=1400.0, broker=name)]
        self.positions: dict = {}
        self.orders = [{"order_id": "O1", "symbol": "TCS", "side": "BUY", "quantity": 5, "price": 3000.0,
                        "trigger_price": 0.0, "status": "open"}]

    async def get_holdings(self):
        return self.holdings

    async def get_positions(self):
        return self.positions

    async def get_orders(self):
        return self.orders

    async def place_order(self, order):
        self.calls.append(("place", order))
        return "B1"

    async def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))

    async def modify_order(self, order_id, quantity=None, price=None, trigger_price=None):
        self.calls.append(("modify", order_id, quantity, price))


@pytest.fixture
def env(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    mine, ai = _Broker("upstox"), _Broker("kite")

    async def mine_adapter(user_id, credentials):
        return mine

    async def mark(symbol):
        return 1500.0

    monkeypatch.setattr(account_actions, "mine_adapter", mine_adapter)
    monkeypatch.setattr(actions, "_mark_price", mark)
    monkeypatch.setattr(actions, "_now", lambda: OPEN)
    return {"db": db, "mine": mine, "ai": ai}


def _tools(db):
    return {t.name: t for t in action_tools(db, None, "alice", "do it")}


async def _card(db, tool, args):
    out = await _tools(db)[tool].ainvoke(args)
    assert out.startswith("ACTION_CARD:"), out
    return json.loads(out[len("ACTION_CARD:"):])


async def test_exit_card_checks_holding_at_propose_and_confirm(env):
    db, mine = env["db"], env["mine"]
    assert "you hold 10" in (await _tools(db)["propose_exit"].ainvoke({"symbol": "INFY", "quantity": 15})).lower()
    assert "don't hold" in (await _tools(db)["propose_exit"].ainvoke({"symbol": "SBIN"})).lower()
    card = await _card(db, "propose_exit", {"symbol": "INFY"})
    assert card["kind"] == "exit" and "10 INFY" in card["summary"]
    assert (await confirm(db, None, None, "alice", card["id"]))["status"] == "NEEDS_SECOND_TAP"
    mine.holdings = []  # sold elsewhere before the second tap
    with pytest.raises(ActionRefused):
        await confirm(db, None, None, "alice", card["id"], second_tap=True)
    assert mine.calls == []


async def test_exit_sells_on_the_users_account(env):
    db, mine = env["db"], env["mine"]
    card = await _card(db, "propose_exit", {"symbol": "INFY", "quantity": 4})
    await confirm(db, None, None, "alice", card["id"])
    result = await confirm(db, None, None, "alice", card["id"], second_tap=True)
    assert result["status"] == "CONFIRMED"
    (kind, order), = mine.calls
    assert kind == "place" and order.side == Side.SELL and order.quantity == 4 and order.product == "CNC"


async def test_cancel_and_modify_reach_only_the_mine_adapter(env):
    db, mine, ai = env["db"], env["mine"], env["ai"]
    assert "no open order" in (await _tools(db)["propose_cancel_order"].ainvoke({"order_id": "NOPE"})).lower()
    for tool, args in (("propose_cancel_order", {"order_id": "O1"}),
                       ("propose_modify_order", {"order_id": "O1", "price": 2990.0})):
        card = await _card(db, tool, args)
        await confirm(db, None, None, "alice", card["id"])
        await confirm(db, None, None, "alice", card["id"], second_tap=True)
    assert mine.calls == [("cancel", "O1"), ("modify", "O1", None, 2990.0)]
    assert ai.calls == []


async def test_stop_loss_refuses_a_trigger_above_the_price_for_a_long(env):
    db, mine = env["db"], env["mine"]
    assert "below" in (await _tools(db)["propose_stop_loss"].ainvoke({"symbol": "INFY", "trigger_price": 1600.0})).lower()
    card = await _card(db, "propose_stop_loss", {"symbol": "INFY", "trigger_price": 1400.0})
    await confirm(db, None, None, "alice", card["id"])
    await confirm(db, None, None, "alice", card["id"], second_tap=True)
    (kind, order), = mine.calls
    assert order.order_type == "SL-M" and order.trigger_price == 1400.0 and order.side == Side.SELL
    assert order.quantity == 10


async def test_upstox_place_order_sends_sl_m_fields(monkeypatch):
    from backend.brokers.upstox import UpstoxAdapter
    from backend.core.models import Order

    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"data": {"order_id": "U1"}})

    adapter = UpstoxAdapter(api_key="k", api_secret="s", redirect_uri="r", redis=None, user_id="alice")

    async def token():
        return "t"

    async def resolve(instrument):
        return {"instrument_key": "NSE_EQ|INE009A01021"}

    monkeypatch.setattr(adapter, "get_access_token", token)
    monkeypatch.setattr(adapter, "_resolve", resolve)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    order = Order(id="x", symbol="INFY", side=Side.SELL, quantity=10, order_type="SL-M", trigger_price=1400.0,
                  product="CNC")
    assert await adapter.place_order(order) == "U1"
    assert sent["order_type"] == "SL-M" and sent["trigger_price"] == 1400.0



async def test_exit_of_a_todays_delivery_buy_keeps_cnc(env):
    db, mine = env["db"], env["mine"]
    mine.holdings = []
    mine.positions = {"INFY": Position(symbol="INFY", quantity=10, avg_price=1500.0, product="CNC")}
    card = await _card(db, "propose_exit", {"symbol": "INFY"})
    await confirm(db, None, None, "alice", card["id"])
    await confirm(db, None, None, "alice", card["id"], second_tap=True)
    (kind, order), = mine.calls
    assert order.product == "CNC"  # selling MIS would open an intraday short
