"""Phase 12 beta metrics: weekly return and opening the journal after a loss."""

from datetime import datetime

from mongomock_motor import AsyncMongoMockClient

from backend.brokers.trades import parse_ist
from backend.core.models import BrokerTrade, Side
from backend.journal.beta import beta_metrics, record_open
from backend.journal.store import JournalStore


def _at(day, hh=10):
    return parse_ist(datetime(2026, 9, day, hh, 0))


async def test_metrics():
    db = AsyncMongoMockClient()["test_db"]
    await db["users"].insert_many([{"id": "alice"}, {"id": "bob"}, {"id": "carol"}])
    # alice: losing day on the 14th, opens the journal on the 15th and in both weeks.
    await JournalStore(db).add_trades("alice", "kite", [
        BrokerTrade(trade_id="1", symbol="SBIN", side=Side.BUY, quantity=1, price=100, traded_at=_at(14)),
        BrokerTrade(trade_id="2", symbol="SBIN", side=Side.SELL, quantity=1, price=90, traded_at=_at(14, 11)),
        BrokerTrade(trade_id="3", symbol="SBIN", side=Side.BUY, quantity=1, price=100, traded_at=_at(21)),
        BrokerTrade(trade_id="4", symbol="SBIN", side=Side.SELL, quantity=1, price=80, traded_at=_at(21, 11)),
    ], source="sync")
    await record_open(db, "alice", _at(15))
    await record_open(db, "alice", _at(15, 15))  # same day counts once
    await record_open(db, "alice", _at(25))
    await record_open(db, "bob", _at(10))  # active two weeks ago only
    await db["user_prefs"].insert_one({"user_id": "alice", "guardrails_enabled": True})

    m = await beta_metrics(db, now=_at(26))
    assert m["users"] == 3
    assert m["users_with_trades"] == 1
    assert m["weekly_active"] == 1  # alice (25th); week = 20th..26th
    assert m["active_last_week"] == 1  # alice (15th); 13th..19th
    assert m["returned_from_last_week"] == 1
    assert m["guardrails_on"] == 1
    assert m["losing_days"] == 2  # 14th and 21st
    assert m["losing_days_followed_by_open"] == 1  # 15th follows the 14th; the 25th is too late for the 21st
    assert await db["journal_opens"].count_documents({}) == 3
