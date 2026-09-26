"""The periodic push: prices for watched symbols, P&L for open dashboards.

One pass serves every viewer, so the thing worth pinning is that it polls
only what someone is actually looking at -- an unwatched universe must not
generate quote traffic every 15 seconds.
"""

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Position
from backend.engine.persistence import LedgerStore
from backend.ws import pump as pump_module
from backend.ws.hub import Hub


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def hub(monkeypatch):
    fresh = Hub()
    monkeypatch.setattr(pump_module, "hub", fresh)
    return fresh


@pytest.fixture
def quotes(monkeypatch):
    asked = []

    async def fake_marks(db, symbols):
        symbols = list(symbols)
        asked.append(symbols)
        return {symbol: 111.0 for symbol in symbols}

    monkeypatch.setattr(pump_module, "mark_prices", fake_marks)
    return asked


@pytest.mark.asyncio
async def test_a_tick_reaches_everyone_watching_that_symbol(mongo, hub, quotes):
    alice = hub.connect("alice")
    alice.subscribe(["prices:RELIANCE"])
    bob = hub.connect("bob")
    bob.subscribe(["prices:RELIANCE"])

    await pump_module.push_once(mongo)

    for connection in (alice, bob):
        message = connection.queue.get_nowait()
        assert message["topic"] == "prices:RELIANCE"
        assert message["data"]["price"] == 111.0


@pytest.mark.asyncio
async def test_nothing_is_polled_when_nobody_is_watching(mongo, hub, quotes):
    result = await pump_module.push_once(mongo)

    assert quotes == []
    assert result == {"symbols": 0, "pnl_users": 0}


@pytest.mark.asyncio
async def test_a_symbol_only_one_user_watches_is_polled_once(mongo, hub, quotes):
    alice = hub.connect("alice")
    alice.subscribe(["prices:RELIANCE", "prices:TCS"])
    bob = hub.connect("bob")
    bob.subscribe(["prices:RELIANCE"])

    await pump_module.push_once(mongo)

    assert sorted(quotes[0]) == ["RELIANCE", "TCS"]


@pytest.mark.asyncio
async def test_pnl_subscribers_get_a_recomputed_snapshot(mongo, hub, quotes):
    ledger = LedgerStore(mongo, user_id="alice")
    await ledger.snapshot_positions({"RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0)})
    connection = hub.connect("alice")
    connection.subscribe(["pnl"])

    await pump_module.push_once(mongo)

    message = connection.queue.get_nowait()
    assert message["topic"] == "pnl"
    # Marked at 111 against a 100 average: 10 shares, 110 rupees unrealized.
    # An untagged position is paper, so it lands in that book only.
    assert message["data"]["paper"]["today"]["unrealized"] == pytest.approx(110.0)
    assert message["data"]["paper"]["open"]["positions"] == 1
    assert message["data"]["live"]["open"]["positions"] == 0
    # A pre-venue browser still finds the combined figures where it looks.
    assert message["data"]["open"]["positions"] == 1


@pytest.mark.asyncio
async def test_pnl_keeps_live_and_paper_books_apart(mongo, hub, quotes):
    ledger = LedgerStore(mongo, user_id="alice")
    await ledger.snapshot_positions({
        "RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0, venue="live"),
        "TCS": Position(symbol="TCS", quantity=5.0, avg_price=100.0, venue="paper"),
    })
    connection = hub.connect("alice")
    connection.subscribe(["pnl"])

    await pump_module.push_once(mongo)

    data = connection.queue.get_nowait()["data"]
    assert data["live"]["open"]["positions"] == 1
    assert data["live"]["today"]["unrealized"] == pytest.approx(110.0)
    assert data["paper"]["open"]["positions"] == 1
    assert data["paper"]["today"]["unrealized"] == pytest.approx(55.0)


@pytest.mark.asyncio
async def test_pnl_does_not_leak_between_users(mongo, hub, quotes):
    alice_ledger = LedgerStore(mongo, user_id="alice")
    await alice_ledger.snapshot_positions({"RELIANCE": Position(symbol="RELIANCE", quantity=10.0, avg_price=100.0)})
    bob = hub.connect("bob")
    bob.subscribe(["pnl"])

    await pump_module.push_once(mongo)

    data = bob.queue.get_nowait()["data"]
    assert data["paper"]["open"]["positions"] == 0
    assert data["live"]["open"]["positions"] == 0
