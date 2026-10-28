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
    await history.write_all(db, NOW)  # second pass rewrites the same rows (idempotent)
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 3


# ---- final-review fixes (C1, I1, I2)


async def test_a_later_import_rewrites_the_past(db):
    """C1 probe: bob's curve starts at his snapshot gap lot (4 @90); importing an
    older buy must fix the stored past rows, not only today's."""
    await history.write_all(db, NOW)
    assert (await db["mine_daily"].find_one({"user_id": "bob", "date": D2.isoformat()}))["invested"] == 360
    await db["journal_trades"].insert_one(_trade("A", "BUY", 4, 80, D1, user="bob"))
    await history.write_all(db, NOW)
    rows = await history.series(db, "bob", None)
    assert [r["date"] for r in rows] == [D1.isoformat(), D2.isoformat(), D3.isoformat()]
    assert [r["invested"] for r in rows] == [320, 320, 320] and not rows[1]["partial"]


async def test_a_removed_trade_drops_its_stored_days(db):
    """R1: bob's D1 buy is undone; his curve starts at the snapshot again, so the D1 row must go."""
    await db["journal_trades"].insert_one(_trade("A", "BUY", 4, 80, D1, user="bob"))
    await history.write_all(db, NOW)
    await db["journal_trades"].delete_one({"user_id": "bob"})
    await history.write_all(db, NOW)
    assert [r["date"] for r in await history.series(db, "bob", None)] == [D2.isoformat(), D3.isoformat()]
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 3  # others untouched


async def test_a_sell_of_pre_journal_shares_is_clipped(db):
    """I1 probe: SELL 10 before any journal buy, then BUY 10 -> no negative invested or value."""
    await db["journal_trades"].insert_many([_trade("A", "SELL", 10, 100, D1, user="carol"),
                                            _trade("A", "BUY", 10, 120, D3, user="carol")])
    await history.backfill(db, "carol", D3)
    rows = await history.series(db, "carol", None)
    # The unmatched sell is dropped, so the curve starts at the buy.
    assert [(r["date"], r["invested"], r["value"], r["nifty_value"]) for r in rows] == [(D3.isoformat(), 1200, 1200, 1200)]
    assert rows[-1]["by_symbol"] == {"A": {"qty": 10, "value": 1200}}


async def test_a_sell_of_the_gap_lot_leaves_the_curve(db):
    """bob's 4 shares predate the journal (gap lot at his snapshot); selling them must empty the curve."""
    await db["journal_trades"].insert_one(_trade("A", "SELL", 4, 120, D3, user="bob"))
    await history.backfill(db, "bob", D3)
    rows = await history.series(db, "bob", None)
    assert rows[-1]["by_symbol"] == {} and rows[-1]["value"] == 0 and rows[-1]["invested"] == -120


async def test_a_bonus_scales_journal_events_to_the_adjusted_bars(db):
    """I2: 10 @200 in the journal, broker now 20 @100 (1:1 bonus), bars split-adjusted."""
    await db["journal_trades"].insert_one(_trade("A", "BUY", 10, 200, D1, user="carol"))
    await db["portfolio_snapshots"].insert_one(
        _snap("carol", D3, [{"symbol": "A", "quantity": 20, "avg_price": 100, "broker": "upstox", "kind": "STOCK"}]))
    await history.backfill(db, "carol", D3)
    rows = await history.series(db, "carol", None)
    assert rows[0]["by_symbol"] == {"A": {"qty": 20, "value": 2000}} and rows[0]["invested"] == 2000
    assert rows[-1]["invested"] == 2000 and rows[-1]["value"] == 2400 and not rows[-1]["partial"]


async def test_selling_everything_after_a_gain_leaves_nifty_at_zero_not_negative(db):
    await db["journal_trades"].insert_one(_trade("A", "SELL", 10, 120, D3))
    await history.backfill(db, "alice", D3)
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D3.isoformat()})
    assert row["value"] == 0 and row["nifty_value"] == 0 and row["invested"] == -200


async def test_a_partial_sale_halves_the_nifty_replica(db):
    await db["journal_trades"].insert_one(_trade("A", "SELL", 5, 120, D3))
    await history.backfill(db, "alice", D3)
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D3.isoformat()})
    assert row["nifty_value"] == pytest.approx(550)  # 1 unit at 1100, half sold


async def test_a_same_day_sell_listed_before_its_buy_is_replayed_after_it(db):
    await db["journal_trades"].insert_many([
        _trade("A", "SELL", 4, 100, D2, user="dan"), _trade("A", "BUY", 4, 100, D2, user="dan")])
    await db["user_prefs"].insert_one({"user_id": "dan", "broker_roles": {"upstox": "mine"}})
    for t in await db["journal_trades"].find({"user_id": "dan"}).to_list(length=None):
        await db["journal_trades"].update_one({"_id": t["_id"]}, {"$set": {"traded_at": datetime(2026, 10, 6, 9, 15, tzinfo=IST)}})
    await history.backfill(db, "dan", D3)
    rows = await history.series(db, "dan", None)
    assert rows and rows[-1]["by_symbol"] == {}  # bought and sold: nothing invented as still held


async def test_an_empty_replay_clears_the_stored_curve(db):
    await history.backfill(db, "alice", D3)
    assert await db["mine_daily"].count_documents({"user_id": "alice"})
    await db["journal_trades"].delete_many({"user_id": "alice"})
    await db["portfolio_snapshots"].delete_many({"user_id": "alice"})
    await history.backfill(db, "alice", D3)
    assert await db["mine_daily"].count_documents({"user_id": "alice"}) == 0
