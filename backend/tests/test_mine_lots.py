from datetime import date, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.session import IST
from backend.mine import lots

D1, D2, D3 = date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)


def _t(side, sym, qty, price, day, broker="upstox"):
    return {"symbol": sym, "side": side, "quantity": qty, "price": price, "broker": broker,
            "traded_at": datetime(day.year, day.month, day.day, 10, tzinfo=IST)}


def buy(*a, **k):
    return _t("BUY", *a, **k)


def sell(*a, **k):
    return _t("SELL", *a, **k)


def test_realised_matches_oldest_first():
    rows = lots.realised([buy("A", 10, 100, D1), buy("A", 10, 120, D2), sell("A", 15, 150, D3)], "A")
    assert [(r["qty"], r["buy_price"]) for r in rows] == [(10, 100), (5, 120)]
    assert sum(r["gain"] for r in rows) == 10 * 50 + 5 * 30
    assert rows[0]["buy_date"] == D1 and rows[0]["sell_date"] == D3


def test_realised_ignores_a_sell_with_no_lot():
    assert lots.realised([sell("A", 5, 150, D3)], "A") == []


def test_open_lots_after_sells():
    assert lots.open_lots([buy("A", 10, 100, D1), sell("A", 4, 150, D2)], "A") == [(D1, 6, 100)]


def test_reconcile_journal_short_of_broker_is_unknown():
    assert lots.reconcile([(D1, 6, 100)], 10, 100) == ([(D1, 6, 100)], 4)


def test_reconcile_journal_over_broker_drops_oldest():
    assert lots.reconcile([(D1, 5, 100), (D2, 5, 110)], 7, 105) == ([(D1, 2, 100), (D2, 5, 110)], 0)


def test_reconcile_split_scales_lots():
    assert lots.reconcile([(D1, 10, 500)], 50, 100) == ([(D1, 50, 100)], 0)


def test_reconcile_nothing_held_drops_all():
    assert lots.reconcile([(D1, 5, 100)], 0, None) == ([], 0)


def test_reconcile_pre_journal_lot_is_not_a_split():
    """I3 probe: journal 10 @1000 (2025), broker 20 at the same average -> 10 bought before the journal."""
    j = date(2025, 1, 1)
    assert lots.reconcile([(j, 10, 1000)], 20, 1000) == ([(j, 10, 1000)], 10)


def test_reconcile_split_needs_broker_avg_to_match():
    assert lots.reconcile([(D1, 10, 500)], 50, 101) == ([(D1, 50, 100)], 0)  # within 2%
    assert lots.reconcile([(D1, 10, 500)], 50, 110) == ([(D1, 10, 500)], 40)  # avg off: unknown
    assert lots.reconcile([(D1, 10, 500)], 50, None) == ([(D1, 10, 500)], 40)  # no avg: unknown


def test_unmatched_sells_are_returned():
    """I4: a sell with no journal lot left is reported, not silently dropped."""
    out = lots.unmatched([sell("A", 5, 150, D1), buy("A", 10, 100, D2), sell("A", 12, 160, D3)], "A")
    assert out == [(D1, 5, 150), (D3, 2, 160)]


def test_scorecard_still_uses_open_lots():
    from backend.portfolio import scorecard
    assert scorecard.open_lots is lots.open_lots


@pytest.fixture
async def db():
    db = AsyncMongoMockClient()["t"]
    await db["user_prefs"].insert_one({"user_id": "alice", "broker_roles": {"upstox": "mine", "kite": "ai"}})
    await db["journal_trades"].insert_many([
        {**buy("A", 1, 1, D1, "upstox"), "user_id": "alice", "_id": "1"},
        {**buy("B", 1, 1, D1, "kite"), "user_id": "alice", "_id": "2"},
        {**buy("C", 1, 1, D1, "upstox"), "user_id": "bob", "_id": "3"},
    ])
    return db


async def test_mine_trades_only_mine_brokers(db):
    assert {t["broker"] for t in await lots.mine_trades(db, "alice")} == {"upstox"}
    assert {t["symbol"] for t in await lots.mine_trades(db, "alice")} == {"A"}


async def test_mine_trades_leave_out_options_and_futures(db):
    """F&O round trips are not holdings and not capital gains: Tax must not tax them at 20% STCG."""
    await db["journal_trades"].insert_many([
        {**buy("NIFTY24OCT25000CE", 50, 100, D1, "upstox"), "exchange": "NFO", "user_id": "alice", "_id": "4"},
        {**buy("RELIANCE24OCTFUT", 250, 3000, D1, "upstox"), "exchange": "NFO", "user_id": "alice", "_id": "5"},
    ])
    assert {t["symbol"] for t in await lots.mine_trades(db, "alice")} == {"A"}
