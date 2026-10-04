"""Resting paper limit orders: fill once when the price crosses, at the
better of mark and limit; expire at 15:30; owner-only cancel."""

import asyncio
from datetime import datetime, timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine import paper_orders
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.suggestions.service import execute_suggestion

OPEN = datetime(2026, 10, 5, 10, 0, tzinfo=IST)


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


def _params(symbol="ITC", side="BUY", quantity=10, limit=400.0, product="CNC"):
    return {"symbol": symbol, "side": side, "quantity": quantity, "product": product,
            "order_type": "LIMIT", "limit_price": limit, "venue": "paper"}


def _marks(**prices):
    async def mark(symbol):
        value = prices[symbol]
        if isinstance(value, Exception):
            raise value
        return value
    return mark


async def _trades(db, user="alice"):
    return await LedgerStore(db, user_id=user).get_trades()


async def test_marketable_buy_fills_now_at_min_of_mark_and_limit(db):
    placed = await paper_orders.place(db, "alice", _params(limit=405.0), 400.0, OPEN)
    assert (placed["status"], placed["fill_price"]) == ("FILLED", 400.0)
    assert len(await _trades(db)) == 1


async def test_resting_buy_fills_on_cross(db):
    placed = await paper_orders.place(db, "alice", _params(limit=400.0), 412.0, OPEN)
    assert placed["status"] == "OPEN" and await _trades(db) == []
    assert await paper_orders.sweep(db, _marks(ITC=399.0), OPEN + timedelta(minutes=1)) == 1
    doc = await db["paper_orders"].find_one({"id": placed["id"]})
    assert (doc["status"], doc["fill_price"]) == ("FILLED", 399.0)
    assert len(await _trades(db)) == 1


async def test_no_fill_while_not_crossed(db):
    placed = await paper_orders.place(db, "alice", _params(limit=400.0), 412.0, OPEN)
    assert await paper_orders.sweep(db, _marks(ITC=401.0), OPEN) == 0
    assert (await db["paper_orders"].find_one({"id": placed["id"]}))["status"] == "OPEN"


async def test_expires_at_close(db):
    placed = await paper_orders.place(db, "alice", _params(), 412.0, OPEN)
    await paper_orders.sweep(db, _marks(ITC=412.0), OPEN.replace(hour=15, minute=30))
    assert (await db["paper_orders"].find_one({"id": placed["id"]}))["status"] == "EXPIRED"


async def test_expires_on_a_later_session(db):
    placed = await paper_orders.place(db, "alice", _params(), 412.0, OPEN - timedelta(days=1))
    await paper_orders.sweep(db, _marks(ITC=399.0), OPEN)
    assert (await db["paper_orders"].find_one({"id": placed["id"]}))["status"] == "EXPIRED"
    assert await _trades(db) == []


async def test_cancel_owner_only(db):
    placed = await paper_orders.place(db, "alice", _params(), 412.0, OPEN)
    assert await paper_orders.cancel(db, "bob", placed["id"]) is False
    assert await paper_orders.cancel(db, "alice", placed["id"]) is True
    await paper_orders.sweep(db, _marks(ITC=399.0), OPEN)
    assert (await db["paper_orders"].find_one({"id": placed["id"]}))["status"] == "CANCELLED"
    assert await _trades(db) == []


async def test_concurrent_sweeps_fill_once(db):
    await paper_orders.place(db, "alice", _params(), 412.0, OPEN)
    mark = _marks(ITC=399.0)
    await asyncio.gather(paper_orders.sweep(db, mark, OPEN), paper_orders.sweep(db, mark, OPEN))
    assert len(await _trades(db)) == 1


async def test_cnc_sell_no_longer_held_is_cancelled(db):
    ledger = LedgerStore(db, user_id="alice")
    await execute_suggestion({"symbol": "ITC", "side": "BUY", "quantity": 3, "mode": "LONGTERM"}, ledger, 400.0)
    placed = await paper_orders.place(db, "alice", _params(side="SELL", quantity=3, limit=420.0), 400.0, OPEN)
    assert placed["status"] == "OPEN"
    await execute_suggestion({"symbol": "ITC", "side": "SELL", "quantity": 3, "mode": "LONGTERM"}, ledger, 405.0)
    await paper_orders.sweep(db, _marks(ITC=421.0), OPEN)
    doc = await db["paper_orders"].find_one({"id": placed["id"]})
    assert (doc["status"], doc["reason"]) == ("CANCELLED", "no longer held")


async def test_mark_failure_skips_symbol_only(db):
    await paper_orders.place(db, "alice", _params(symbol="ITC"), 412.0, OPEN)
    await paper_orders.place(db, "alice", _params(symbol="INFY", limit=1500.0), 1600.0, OPEN)
    changed = await paper_orders.sweep(db, _marks(ITC=RuntimeError("no quote"), INFY=1490.0), OPEN)
    assert changed == 1


async def test_list_open_is_per_user(db):
    await paper_orders.place(db, "alice", _params(), 412.0, OPEN)
    await paper_orders.place(db, "bob", _params(), 412.0, OPEN)
    mine = await paper_orders.list_open(db, "alice")
    assert [o["user_id"] for o in mine] == ["alice"] and "_id" not in mine[0]
