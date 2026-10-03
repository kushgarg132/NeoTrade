"""Approved long-term paper positions close at their stop or target."""

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
    await execute_suggestion(suggestion, LedgerStore(db, user_id="alice"), price=100.0, now=NOW)


def _marks(prices):
    async def fn(db, symbols):
        return {s: prices[s] for s in symbols if s in prices}
    return fn


@pytest.mark.asyncio
async def test_positions_close_at_stop_and_target_and_others_stay_open():
    db = AsyncMongoMockClient()["test_db"]
    for symbol in ("LOSER", "WINNER", "HOLD"):
        await _approved(db, symbol)

    closed = await check_exits(db, "alice", now=NOW, marks_fn=_marks({"LOSER": 88.0, "WINNER": 121.0, "HOLD": 100.0}))

    assert sorted((c["symbol"], c["reason"]) for c in closed) == [("LOSER", "stop"), ("WINNER", "target")]
    ledger = LedgerStore(db, user_id="alice")
    assert [t["symbol"] for t in await ledger.get_trades(status="OPEN")] == ["HOLD"]
    done = {t["symbol"]: t for t in await ledger.get_trades(status="CLOSED")}
    assert done["WINNER"]["realized_pnl"] == pytest.approx(210.0)
    assert done["WINNER"]["strategy"] == "breakout"


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
