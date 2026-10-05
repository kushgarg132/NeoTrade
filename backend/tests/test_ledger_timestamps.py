"""Ledger reads hand back UTC-aware datetimes. Mongo returns naive UTC; sent
to the browser without an offset, "06:55" was read as 06:55 IST -- every
execution time on Practice -> Book was 5h30m early."""

from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Fill, Side
from backend.engine.persistence import LedgerStore


async def test_fills_come_back_utc_aware():
    db = AsyncMongoMockClient()["test_db"]
    ledger = LedgerStore(db, user_id="alice")
    when = datetime(2026, 10, 5, 6, 55, tzinfo=timezone.utc)
    await ledger.fills.insert_one({
        **Fill(order_id="o1", symbol="ITC", side=Side.BUY, quantity=1, price=100.0, timestamp=when, costs=0.0).model_dump(),
        "user_id": "alice",
    })
    (fill,) = await ledger.get_fills()
    assert fill.timestamp.tzinfo is not None
    assert fill.timestamp == when
    assert fill.model_dump(mode="json")["timestamp"].endswith(("Z", "+00:00"))
