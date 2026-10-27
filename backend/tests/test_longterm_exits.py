from datetime import datetime, timedelta, timezone

from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.persistence import LedgerStore
from backend.suggestions.exits import breach, check_exits
from backend.suggestions.service import execute_suggestion

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)


def test_breach_picks_stop_target_or_nothing():
    assert breach(89.0, 90.0, 120.0) == "stop"
    assert breach(120.0, 90.0, 120.0) == "target"
    assert breach(100.0, 90.0, 120.0) is None
    assert breach(100.0, None, None) is None


async def _approved(db, symbol, mode="LONGTERM"):
    suggestion = {
        "id": f"s-{symbol}", "user_id": "alice", "symbol": symbol, "side": "BUY", "mode": mode,
        "quantity": 10.0, "stop": 90.0, "target": 120.0, "strategy": "breakout", "option_contract": None,
    }
    await db["suggestions"].insert_one(dict(suggestion))
    # Approved with real money on the user's own account, and in its holdings.
    await execute_suggestion(suggestion, LedgerStore(db, user_id="alice:mine"), price=100.0, now=NOW)
    await db["portfolio_snapshots"].update_one(
        {"user_id": "alice"}, {"$set": {"at": NOW}, "$push": {"raw_holdings": {"symbol": symbol, "quantity": 10.0, "broker": "upstox"}}},
        upsert=True)


def _marks(prices):
    async def fn(db, symbols):
        return {s: prices[s] for s in symbols if s in prices}
    return fn




@pytest.mark.asyncio
async def test_intraday_trades_and_missing_marks_are_left_alone():
    db = AsyncMongoMockClient()["test_db"]
    await _approved(db, "INTRA", mode="INTRADAY")
    await _approved(db, "NOMARK")
    assert await check_exits(db, "alice", now=NOW, marks_fn=_marks({"INTRA": 50.0})) == []


def test_alert_texts_name_the_trade():
    from backend.suggestions.notify import exits_text, proposals_text

    text = proposals_text([{"side": "BUY", "symbol": "SJVN", "quantity": 21.0, "entry_ref": 57.91,
                            "stop": 55.01, "target": 60.81}], "1 new:")
    assert "BUY SJVN x21 @ ~₹57.91 · stop ₹55.01 · target ₹60.81" in text
    assert proposals_text([{"id": "bare"}], "x")  # sparse rows never raise
    assert "SJVN x10 at ₹60.00 (target)" in exits_text([{"symbol": "SJVN", "reason": "target", "price": 60.0,
                                                         "quantity": 10.0, "entry_price": 55.0, "gross_pnl": 50.0}])


def test_max_hold_counts_trading_days():
    from backend.suggestions.exits import held_too_long

    fri = datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)  # Fri 10:30 IST
    assert not held_too_long(fri, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), 1)  # same day
    assert not held_too_long(fri, datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc), 1)  # Sunday: no weekday yet
    assert held_too_long(fri, datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc), 1)      # Monday counts 1
    assert not held_too_long(fri, datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc), 3)  # Mon, Tue = 2
    assert held_too_long(fri, datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc), 3)      # + Wed = 3
    # 20:00 UTC Friday is already Saturday in IST: the count starts after Saturday.
    late = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)
    assert not held_too_long(late, datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc), 3)
    assert held_too_long(fri.replace(tzinfo=None), datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc), 1)  # naive = UTC
    # Tue 2026-10-20 is an NSE holiday: from Monday's entry, Wednesday is day 1, not day 2.
    mon = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
    assert not held_too_long(mon, datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc), 2)
    assert held_too_long(mon, datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc), 2)


async def _bars(db, symbol, rows):
    """rows of (IST date, high, low, close)."""
    await db["daily_bars"].insert_many([
        {"symbol": symbol, "date": d, "open": c, "high": h, "low": l, "close": c, "volume": 1000}
        for d, h, l, c in rows])


@pytest.mark.asyncio
async def test_trailing_stop_only_rises():
    from datetime import date, timedelta as td
    from backend.suggestions.exits import trail_level

    assert trail_level(120.0, 5.0, 2.0) == 110.0
    db = AsyncMongoMockClient()["test_db"]
    await _approved(db, "TRAIL")
    await _approved(db, "NOBARS")
    await db["suggestions"].update_many({}, {"$set": {"trail_atr": 2.0}})
    # 20 bars before entry (true range 5), then closes up to 120 since entry (NOW is 2026-10-05).
    days = [date(2026, 10, 5) - td(days=20 - i) for i in range(20)] + [date(2026, 10, 5) + td(days=i) for i in range(3)]
    closes = [100.0] * 20 + [110.0, 120.0, 115.0]
    await _bars(db, "TRAIL", [(d.isoformat(), c + 2.5, c - 2.5, c) for d, c in zip(days, closes)])
    later = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)

    # ATR: the last 14 true ranges -- 11 of 5, then 12.5, 12.5, 7.5 (gaps up and back) => 6.25.
    # Trail = 120 - 2 x 6.25 = 107.5, above the original stop of 90.
    assert await check_exits(db, "alice", now=later, marks_fn=_marks({"TRAIL": 108.0, "NOBARS": 95.0})) == []
    trade = await db["paper_trades"].find_one({"symbol": "TRAIL"})
    assert trade["trail_stop"] == pytest.approx(107.5)
    assert "trail_stop" not in await db["paper_trades"].find_one({"symbol": "NOBARS"})  # no bars: original stop

    # A stored trail above today's never comes down, and a mark under it exits as a trailing stop.
    await db["paper_trades"].update_one({"symbol": "TRAIL"}, {"$set": {"trail_stop": 112.0}})
    closed = await check_exits(db, "alice", now=later, marks_fn=_marks({"TRAIL": 111.0, "NOBARS": 89.0}))
    assert sorted((c["symbol"], c["reason"]) for c in closed) == [("NOBARS", "stop"), ("TRAIL", "trailing stop")]
    assert (await db["paper_trades"].find_one({"symbol": "TRAIL"}))["trail_stop"] == 112.0


@pytest.mark.asyncio
async def test_a_failing_trail_never_blocks_other_exits(monkeypatch):
    from backend.suggestions import exits

    db = AsyncMongoMockClient()["test_db"]
    await _approved(db, "BROKEN")
    await _approved(db, "LOSER")
    await db["suggestions"].update_one({"symbol": "BROKEN"}, {"$set": {"trail_atr": 2.0}})
    await _bars(db, "BROKEN", [("2026-10-05", 101.0, 99.0, 100.0)])

    def boom(*a, **k):
        raise ValueError("bad bar")

    monkeypatch.setattr(exits, "_trail_from_bars", boom)
    closed = await check_exits(db, "alice", now=NOW, marks_fn=_marks({"BROKEN": 89.0, "LOSER": 88.0}))
    assert sorted((c["symbol"], c["reason"]) for c in closed) == [("BROKEN", "stop"), ("LOSER", "stop")]

    async def no_bars(*a, **k):
        raise RuntimeError("mongo down")

    await _approved(db, "LOSER2")
    await db["suggestions"].update_one({"symbol": "LOSER2"}, {"$set": {"trail_atr": 2.0}})
    monkeypatch.setattr(exits.bars, "read", no_bars)
    closed = await check_exits(db, "alice", now=NOW, marks_fn=_marks({"LOSER2": 88.0}))
    assert [(c["symbol"], c["reason"]) for c in closed] == [("LOSER2", "stop")]


def test_max_hold_exits_from_the_close_on_the_due_day():
    from backend.suggestions.exits import max_hold_due

    fri = datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)
    ist = lambda d, h, m: datetime(2026, 10, d, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert not max_hold_due(fri, ist(5, 9, 30), 1)  # Monday is due day: morning waits
    assert not max_hold_due(fri, ist(5, 15, 14), 1)
    assert max_hold_due(fri, ist(5, 15, 15), 1)
    assert max_hold_due(fri, ist(6, 9, 30), 1)      # day after due: any time







@pytest.mark.asyncio
async def test_exit_levels_alert_once_and_sell_nothing():
    db = AsyncMongoMockClient()["test_db"]
    for symbol in ("LOSER", "WINNER", "HOLD"):
        await _approved(db, symbol)
    marks = _marks({"LOSER": 88.0, "WINNER": 121.0, "HOLD": 100.0})

    alerts = await check_exits(db, "alice", now=NOW, marks_fn=marks)

    assert sorted((a["symbol"], a["reason"]) for a in alerts) == [("LOSER", "stop"), ("WINNER", "target")]
    # 210 at the bare mark; the entry fill now pays 10 bps slippage (suggestions/service.py::fill_on_paper)
    assert next(a for a in alerts if a["symbol"] == "WINNER")["gross_pnl"] == pytest.approx(209.0)
    assert await check_exits(db, "alice", now=NOW, marks_fn=marks) == []  # once per reason
    assert await db["paper_fills"].count_documents({"side": "SELL"}) == 0  # the user sells, not the app
    assert len(await LedgerStore(db, user_id="alice:mine").get_trades(status="OPEN")) == 3


@pytest.mark.asyncio
async def test_a_stock_sold_in_the_broker_app_closes_its_trade():
    db = AsyncMongoMockClient()["test_db"]
    await _approved(db, "SOLD")
    await _approved(db, "KEPT")
    later = NOW + timedelta(days=1)
    await db["portfolio_snapshots"].insert_one(
        {"user_id": "alice", "at": later, "raw_holdings": [{"symbol": "KEPT", "quantity": 10.0, "broker": "upstox"}]})

    assert await check_exits(db, "alice", now=later, marks_fn=_marks({"SOLD": 80.0, "KEPT": 80.0})) != []
    trades = {t["symbol"]: t["status"] for t in await LedgerStore(db, user_id="alice:mine").get_trades()}
    assert trades == {"SOLD": "CLOSED", "KEPT": "OPEN"}
    sold = await db["paper_trades"].find_one({"symbol": "SOLD"})
    assert sold["closed_by"] == "inferred_from_holdings"


@pytest.mark.asyncio
async def test_a_same_day_buy_missing_from_holdings_is_not_closed_as_sold():
    # A delivery buy shows under positions, not holdings, until it settles.
    db = AsyncMongoMockClient()["test_db"]
    await _approved(db, "TODAY")
    await db["portfolio_snapshots"].insert_one(
        {"user_id": "alice", "at": NOW + timedelta(hours=6), "raw_holdings": []})
    await check_exits(db, "alice", now=NOW + timedelta(hours=7), marks_fn=_marks({"TODAY": 100.0}))
    assert [t["status"] for t in await LedgerStore(db, user_id="alice:mine").get_trades()] == ["OPEN"]


def test_levels_keep_their_distance_but_move_to_the_fill():
    from backend.suggestions.exits import anchored

    # Priced off a ₹100 close with a ₹10 stop distance; filled at ₹106 after a gap up.
    assert anchored(90.0, 100.0, 106.0) == pytest.approx(96.0)
    assert anchored(120.0, 100.0, 106.0) == pytest.approx(126.0)
    # No reference close or no fill (older proposals): the stored level stands.
    assert anchored(90.0, None, 106.0) == 90.0
    assert anchored(90.0, 100.0, None) == 90.0
    assert anchored(None, 100.0, 106.0) is None


@pytest.mark.asyncio
async def test_stop_is_measured_from_the_fill_not_the_proposal_close():
    db = AsyncMongoMockClient()["test_db"]
    suggestion = {"id": "s-GAP", "user_id": "alice", "symbol": "GAP", "side": "BUY", "mode": "LONGTERM",
                  "quantity": 10.0, "entry_ref": 100.0, "stop": 90.0, "target": 120.0, "strategy": "breakout",
                  "option_contract": None}
    await db["suggestions"].insert_one(dict(suggestion))
    # Gapped up: filled near ₹110, so the stop is ~₹100, not ₹90.
    await execute_suggestion(suggestion, LedgerStore(db, user_id="alice:mine"), price=110.0, now=NOW)
    await db["portfolio_snapshots"].update_one({"user_id": "alice"}, {"$set": {"at": NOW}, "$push": {
        "raw_holdings": {"symbol": "GAP", "quantity": 10.0, "broker": "upstox"}}}, upsert=True)
    [alert] = await check_exits(db, "alice", now=NOW, marks_fn=_marks({"GAP": 99.0}))
    assert alert["reason"] == "stop"
    # The target moved up too: ₹125 no longer reaches it.
    db2 = AsyncMongoMockClient()["test_db2"]
    await db2["suggestions"].insert_one(dict(suggestion))
    await execute_suggestion(suggestion, LedgerStore(db2, user_id="alice:mine"), price=110.0, now=NOW)
    await db2["portfolio_snapshots"].update_one({"user_id": "alice"}, {"$set": {"at": NOW}, "$push": {
        "raw_holdings": {"symbol": "GAP", "quantity": 10.0, "broker": "upstox"}}}, upsert=True)
    assert await check_exits(db2, "alice", now=NOW, marks_fn=_marks({"GAP": 125.0})) == []
