"""Daily broker-to-ledger reconciliation (Phase 21): each broker order is
matched to the app's ledger fill and journal row, holdings to the book's open
quantity, and every disagreement is named. Read-only against the broker."""

from datetime import date, datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.brokers.protocol import BrokerSessionState
from backend.core.models import BrokerTrade, Fill, Holding, Position, Side
from backend.engine import broker_recon
from backend.engine.persistence import LedgerStore

DAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 10, 40, tzinfo=timezone.utc)  # 16:10 IST
AT = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)  # 10:30 IST


class _Broker:
    def __init__(self, trades=(), holdings=(), positions=None, state=BrokerSessionState.ACTIVE):
        self.trades, self.holdings, self.positions, self._state = list(trades), list(holdings), positions or {}, state
        self.placed = []

    async def state(self):
        return self._state

    async def get_trades(self):
        return self.trades

    async def get_holdings(self):
        return self.holdings

    async def get_positions(self):
        return self.positions

    async def place_order(self, order):  # must never be called
        self.placed.append(order)
        raise AssertionError("reconciliation placed an order")


def _trade(tid, oid, symbol="ITC", qty=10, price=400.0, side=Side.BUY):
    return BrokerTrade(trade_id=tid, order_id=oid, symbol=symbol, side=side, quantity=qty, price=price, traded_at=AT)


def _fill(oid, symbol="ITC", qty=10, price=400.0):
    return Fill(order_id=oid, symbol=symbol, side=Side.BUY, quantity=qty, price=price, timestamp=AT, venue="live")


def _row(app_id, broker_id, role="ai"):
    return {"_id": app_id, "broker_order_id": broker_id, "role": role}


def _journal(*trades):
    return {t.trade_id: {"symbol": t.symbol, "quantity": t.quantity, "price": t.price} for t in trades}


def _kinds(mismatches):
    return sorted((m["kind"], m["where"], m["symbol"]) for m in mismatches)


def test_a_clean_day_has_no_mismatches():
    t = _trade("T1", "B1")
    assert broker_recon.classify("ai", [t], [_row("A1", "B1")], [_fill("A1")], _journal(t),
                                 {"ITC": 10}, {"ITC": 10}) == []


def test_each_kind_of_mismatch_is_named():
    trades = [
        _trade("T1", "B1"),                      # booked: fine
        _trade("T2", "B2", symbol="TCS"),        # app placed it, ledger never booked it
        _trade("T3", "B3", symbol="INFY", qty=5),  # ledger booked 4
        _trade("T4", "B4", symbol="HDFC", price=110.0),  # ledger booked at 100
        _trade("T5", "B5", symbol="WIPRO"),      # nobody in the app placed it
    ]
    rows = [_row("A1", "B1"), _row("A2", "B2"), _row("A3", "B3"), _row("A4", "B4"), _row("A6", "B6")]
    fills = [_fill("A1"), _fill("A3", symbol="INFY", qty=4), _fill("A4", symbol="HDFC", price=100.0),
             _fill("A6", symbol="SBIN")]  # booked, but the broker has no such order
    journal = _journal(*trades[:4])  # T5 missing from the journal
    journal["T9"] = {"symbol": "LT", "quantity": 1, "price": 1.0}  # journal row the broker no longer shows
    got = broker_recon.classify("ai", trades, rows, fills, journal,
                                broker_qty={"ITC": 10, "TCS": 10, "BEL": 3, "INFY": 5},
                                ledger_qty={"ITC": 10, "SBIN": 10, "INFY": 2})
    assert _kinds(got) == sorted([
        ("missing_in_ledger", "ledger", "TCS"),
        ("quantity_differs", "ledger", "INFY"),
        ("price_differs", "ledger", "HDFC"),
        ("unknown_order", "ledger", "WIPRO"),
        ("missing_at_broker", "ledger", "SBIN"),
        ("missing_in_ledger", "journal", "WIPRO"),
        ("missing_at_broker", "journal", "LT"),
        ("missing_in_ledger", "holdings", "TCS"),
        ("missing_in_ledger", "holdings", "BEL"),
        ("missing_at_broker", "holdings", "SBIN"),
        ("quantity_differs", "holdings", "INFY"),
    ])


def test_the_users_own_account_may_hold_and_trade_more_than_the_app_placed():
    hand = _trade("T1", "B-hand", symbol="TCS")
    got = broker_recon.classify("mine", [hand], [], [], _journal(hand),
                                broker_qty={"TCS": 50, "ITC": 20}, ledger_qty={"ITC": 10})
    assert got == []
    short = broker_recon.classify("mine", [], [], [], {}, broker_qty={"ITC": 5}, ledger_qty={"ITC": 10})
    assert _kinds(short) == [("quantity_differs", "holdings", "ITC")]


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def _seed_ai_day(db):
    await LedgerStore(db, user_id="alice:autopilot").record_fill(_fill("A1"))
    await LedgerStore(db, user_id="alice:autopilot").snapshot_positions(
        {"ITC": Position(symbol="ITC", quantity=10, avg_price=400.0, venue="live")})
    await db["live_orders"].insert_one({"_id": "A1", "broker_order_id": "B1", "user_id": "alice", "role": "ai",
                                        "submitted_at": AT})
    await db["journal_trades"].insert_one({"_id": "alice:kite:T1", "user_id": "alice", "broker": "kite",
                                           "trade_id": "T1", "symbol": "ITC", "quantity": 10, "price": 400.0,
                                           "traded_at": AT})


async def test_a_run_stores_one_doc_per_role_and_a_rerun_replaces_it(db):
    await _seed_ai_day(db)
    ai = _Broker(trades=[_trade("T1", "B1"), _trade("T2", "B2", symbol="TCS")],
                 holdings=[Holding(symbol="ITC", quantity=10, avg_price=400.0, broker="kite")])
    mine = _Broker(state=BrokerSessionState.NEEDS_LOGIN)
    adapters = {"kite": ai, "upstox": mine}

    async def get_adapter(broker):
        return adapters[broker]

    roles = {"kite": "ai", "upstox": "mine"}
    await broker_recon.reconcile_user(db, "alice", roles, get_adapter, DAY, NOW)
    await broker_recon.reconcile_user(db, "alice", roles, get_adapter, DAY, NOW)

    docs = {d["role"]: d for d in await db[broker_recon.COLLECTION].find({}).to_list(length=None)}
    assert set(docs) == {"ai", "mine"}
    assert docs["ai"]["_id"] == "alice:2026-10-16:ai" and docs["ai"]["status"] == "mismatch"
    assert _kinds(docs["ai"]["mismatches"]) == [("missing_in_ledger", "journal", "TCS"),
                                                ("unknown_order", "ledger", "TCS")]
    assert docs["mine"]["status"] == "not_checked" and docs["mine"]["reason"] == "not checked: logged out"
    assert docs["mine"]["broker"] == "upstox"
    assert ai.placed == [] and mine.placed == []

    latest = await broker_recon.latest(db, "alice")
    assert broker_recon.summary(latest) == "AI account: 2 (TCS)"


async def test_a_clean_role_is_ok_and_a_role_nobody_holds_is_skipped(db):
    await _seed_ai_day(db)
    ai = _Broker(trades=[_trade("T1", "B1")], holdings=[Holding(symbol="ITC", quantity=10, avg_price=400.0, broker="kite")])

    async def get_adapter(broker):
        return ai

    docs = await broker_recon.reconcile_user(db, "alice", {"kite": "ai"}, get_adapter, DAY, NOW)
    assert [(d["role"], d["status"]) for d in docs] == [("ai", "ok")]
    assert broker_recon.summary(docs) is None


async def test_a_broker_error_is_recorded_as_not_checked(db):
    class _Down(_Broker):
        async def get_trades(self):
            raise RuntimeError("502")

    async def get_adapter(broker):
        return _Down()

    docs = await broker_recon.reconcile_user(db, "alice", {"kite": "ai"}, get_adapter, DAY, NOW)
    assert docs[0]["status"] == "not_checked" and "RuntimeError" in docs[0]["reason"]


async def test_broker_quantities_sum_both_products_of_a_symbol():
    from backend.engine.broker_recon import _broker_quantities

    broker = _Broker(positions={"ITC": Position(symbol="ITC", quantity=10, avg_price=400.0, product="MIS"),
                                "ITC:CNC": Position(symbol="ITC", quantity=5, avg_price=390.0, product="CNC")})
    assert await _broker_quantities(broker) == {"ITC": 15}

