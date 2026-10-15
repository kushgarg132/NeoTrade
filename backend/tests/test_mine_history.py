from datetime import date, datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.session import IST
from backend.mine import history

D1, D2, D3 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
SNAPSHOT_DAY = D2
NOW = datetime(2026, 10, 7, 16, 0, tzinfo=IST)


def _bar(symbol, day, close):
    return {"symbol": symbol, "date": day.isoformat(), "open": close, "high": close, "low": close,
            "close": close, "volume": 1}


def _trade(symbol, side, qty, price, day, broker="upstox", user="alice"):
    return {"user_id": user, "_id": f"{user}{symbol}{day}{side}", "symbol": symbol, "side": side, "quantity": qty,
            "price": price, "broker": broker, "traded_at": datetime(day.year, day.month, day.day, 10, tzinfo=IST)}


def _snap(user, day, holdings):
    return {"user_id": user, "at": datetime(day.year, day.month, day.day, 17, tzinfo=IST), "raw_holdings": holdings}


@pytest.fixture
async def db():
    db = AsyncMongoMockClient()["t"]
    await db["user_prefs"].insert_many([
        {"user_id": "alice", "broker_roles": {"upstox": "mine"}}, {"user_id": "bob", "broker_roles": {"upstox": "mine"}}])
    await db["journal_trades"].insert_many([_trade("A", "BUY", 10, 100, D1), _trade("OTHER", "BUY", 1, 1, D1, user="eve")])
    await db["daily_bars"].insert_many(
        [_bar("^NSEI", D1, 1000), _bar("^NSEI", D2, 1100), _bar("^NSEI", D3, 1100),
         _bar("A", D1, 100), _bar("A", D2, 110), _bar("A", D3, 120)])
    await db["portfolio_snapshots"].insert_many([
        _snap("alice", D1, [{"symbol": "A", "quantity": 10, "avg_price": 100, "broker": "upstox", "kind": "STOCK"},
                            {"symbol": "FUND", "quantity": 5, "avg_price": 10, "broker": "upstox", "kind": "MF"}]),
        _snap("bob", SNAPSHOT_DAY, [{"symbol": "A", "quantity": 4, "avg_price": 90, "broker": "upstox", "kind": "STOCK"}]),
    ])
    return db


def test_xirr_one_year_ten_percent():
    assert history.xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-4)


def test_xirr_negative_return_and_two_flows():
    assert history.xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 900)]) == pytest.approx(-0.10, abs=1e-4)


def test_xirr_none_without_sign_change():
    assert history.xirr([(date(2025, 1, 1), -1000)]) is None
    assert history.xirr([(date(2025, 1, 1), -1000), (date(2025, 6, 1), -5)]) is None


async def test_backfill_values_and_nifty(db):
    assert await history.backfill(db, "alice", D2) == 2
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D2.isoformat()})
    assert (row["value"], row["invested"], row["nifty_value"]) == (1100, 1000, 1100)
    assert row["by_symbol"] == {"A": {"qty": 10, "value": 1100}} and row["flow"] == 0 and not row["partial"]
    await history.backfill(db, "alice", D2)  # idempotent
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 2


async def test_backfill_missing_bar_carries_close(db):
    await db["daily_bars"].delete_one({"symbol": "A", "date": D2.isoformat()})
    await history.backfill(db, "alice", D2)
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D2.isoformat()})
    assert row["value"] == 1000


async def test_a_sell_is_negative_flow(db):
    await db["journal_trades"].insert_one(_trade("A", "SELL", 4, 120, D3))
    await history.backfill(db, "alice", D3)
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D3.isoformat()})
    assert row["flow"] == -480 and row["invested"] == 520 and row["value"] == 720


async def test_no_trades_starts_at_first_snapshot_partial(db):
    await history.backfill(db, "bob", D3)
    rows = await history.series(db, "bob", None)
    assert rows[0]["date"] == SNAPSHOT_DAY.isoformat() and rows[0]["partial"]
    assert rows[0]["by_symbol"]["A"]["qty"] == 4 and rows[0]["invested"] == 360


async def test_funds_left_out_of_curve(db):
    await history.backfill(db, "alice", D2)
    out = await history.returns(db, "alice", D2)
    assert out["funds_excluded"] is True
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D2.isoformat()})
    assert "FUND" not in row["by_symbol"]


async def test_returns_xirr_and_extra_flows(db):
    # Mild moves: a 2-day 20% gain annualises past the solver's ceiling (None, by design).
    await db["daily_bars"].update_one({"symbol": "A", "date": D3.isoformat()}, {"$set": {"close": 100.5}})
    await db["daily_bars"].update_many({"symbol": "^NSEI", "date": {"$gt": D1.isoformat()}}, {"$set": {"close": 1001}})
    await history.backfill(db, "alice", D3)
    out = await history.returns(db, "alice", D3)
    assert out["xirr"] > 0and out["nifty_xirr"] > 0 and out["from_date"] == D1.isoformat()
    more = await history.returns(db, "alice", D3, [(D3, 1.0)])
    assert more["xirr"] > out["xirr"]


async def test_write_all_scoped_per_user(db):
    await history.write_all(db, NOW)
    assert await db["mine_daily"].count_documents({"user_id": {"$nin": ["alice", "bob"]}}) == 0
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 3
    await history.write_all(db, NOW)  # second pass only refreshes today's row
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 3
