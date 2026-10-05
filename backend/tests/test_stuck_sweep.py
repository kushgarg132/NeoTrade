"""A crash between a claim and its settle used to leave a proposal SENDING,
or a paper limit FILLING, forever. The sweeper checks what actually happened
and fixes the row -- or flags it when it cannot tell, rather than re-arm a
real-money approval that may have reached the broker."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.stuck import sweep_stuck

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(minutes=10)


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def _sending(db, sid, path, at=OLD):
    await db["suggestions"].insert_one({"id": sid, "user_id": "alice", "symbol": "ITC", "status": "SENDING",
                                        "reason": path, "decided_at": at})


async def _status(db, sid):
    return (await db["suggestions"].find_one({"id": sid}))["status"]


async def test_a_paper_claim_with_a_booked_fill_becomes_executed(db):
    await _sending(db, "s1", "paper")
    await db["paper_orders"].insert_one({"id": "o1", "user_id": "alice", "suggestion_id": "s1", "status": "FILLED"})
    await db["paper_fills"].insert_one({"order_id": "o1", "user_id": "alice"})
    await sweep_stuck(db, NOW)
    doc = await db["suggestions"].find_one({"id": "s1"})
    assert (doc["status"], doc["order_id"]) == ("EXECUTED", "o1")


async def test_a_paper_claim_that_placed_nothing_goes_back_to_pending(db):
    await _sending(db, "s2", "paper")
    await sweep_stuck(db, NOW)
    assert await _status(db, "s2") == "PENDING"


async def test_a_live_claim_with_a_broker_order_becomes_sent(db):
    await _sending(db, "s3", "live")
    await db["paper_orders"].insert_one({"id": "o3", "user_id": "alice", "suggestion_id": "s3", "status": "PENDING"})
    await db["live_orders"].insert_one({"_id": "o3", "user_id": "alice", "status": "SUBMITTED"})
    await sweep_stuck(db, NOW)
    assert await _status(db, "s3") == "SENT"


async def test_a_live_claim_with_no_record_is_flagged_never_rearmed(db):
    await _sending(db, "s4", "live")
    await sweep_stuck(db, NOW)
    assert await _status(db, "s4") == "NEEDS_REVIEW"


async def test_a_fresh_claim_is_left_alone(db):
    await _sending(db, "s5", "live", at=NOW - timedelta(minutes=1))
    await sweep_stuck(db, NOW)
    assert await _status(db, "s5") == "SENDING"


async def test_a_paper_limit_stuck_filling_is_settled_from_its_fill(db):
    await db["paper_limit_orders"].insert_many([
        {"id": "L1", "user_id": "alice", "status": "FILLING", "limit_price": 400.0, "claimed_at": OLD},
        {"id": "L2", "user_id": "alice", "status": "FILLING", "limit_price": 400.0, "claimed_at": OLD},
    ])
    await db["paper_fills"].insert_one({"order_id": "L1", "user_id": "alice", "price": 399.5})
    await sweep_stuck(db, NOW)
    l1 = await db["paper_limit_orders"].find_one({"id": "L1"})
    l2 = await db["paper_limit_orders"].find_one({"id": "L2"})
    assert (l1["status"], l1["fill_price"]) == ("FILLED", 399.5)
    assert l2["status"] == "OPEN"
