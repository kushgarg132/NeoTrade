"""query_my_data: the model may read any of the caller's data, never anyone
else's, and never the secret collections."""

import json
from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.chat.tools import read_tools


def _tool(db, user_id="alice"):
    return next(t for t in read_tools(db, None, user_id) if t.name == "query_my_data")


async def _seed():
    db = AsyncMongoMockClient()["test_db"]
    await db.paper_trades.insert_many([
        {"user_id": "alice", "symbol": "INFY", "realized_pnl": -120.0,
         "exit_at": datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)},
        {"user_id": "alice", "symbol": "TCS", "realized_pnl": 300.0,
         "exit_at": datetime(2026, 9, 20, 5, 0, tzinfo=timezone.utc)},
        {"user_id": "bob", "symbol": "INFY", "realized_pnl": 999.0,
         "exit_at": datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)},
    ])
    await db.broker_credentials.insert_one({"user_id": "alice", "api_secret_enc": "s3cret"})
    return db


async def test_reads_only_the_callers_rows_even_when_the_filter_tries_to_widen():
    db = await _seed()
    out = json.loads(await _tool(db).ainvoke({
        "collection": "paper_trades", "filter": {"$or": [{"user_id": "bob"}, {"symbol": "INFY"}]},
    }))
    assert out["matched"] == 1
    assert out["rows"][0]["symbol"] == "INFY" and out["rows"][0]["realized_pnl"] == -120.0
    assert "user_id" not in out["rows"][0] and "_id" not in out["rows"][0]


async def test_secret_collections_and_javascript_are_refused():
    db = await _seed()
    tool = _tool(db)
    refused = await tool.ainvoke({"collection": "broker_credentials"})
    assert refused.startswith("Unknown collection") and "s3cret" not in refused
    assert "not allowed" in await tool.ainvoke({"collection": "paper_trades", "filter": {"$where": "true"}})


async def test_iso_datetimes_filter_datetime_fields():
    db = await _seed()
    out = json.loads(await _tool(db).ainvoke({
        "collection": "paper_trades", "filter": {"exit_at": {"$gte": "2026-10-01T00:00:00+05:30"}},
        "fields": ["symbol"],
    }))
    assert out["rows"] == [{"symbol": "INFY"}]
