from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.forward.store import ForwardStore

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


def kw(**o):
    return dict(source="picks", name="breakout", user_id="system", symbol="TCS", side="BUY",
                decided_at=NOW, intraday=False, ref_price=100.0, horizon_days=5, **o)


async def test_record_is_idempotent():
    db = AsyncMongoMockClient()["t"]
    s = ForwardStore(db)
    assert await s.record(**kw()) is True
    assert await s.record(**kw()) is False
    assert await db["forward_records"].count_documents({}) == 1
    assert await db["forward_records"].find_one({"_id": "picks:breakout:TCS:2026-10-19:BUY"})


async def test_record_failure_returns_false():
    class Col:
        async def update_one(self, *a, **k):
            raise RuntimeError("down")

    class Broken:
        def __getitem__(self, k):
            return Col()

    assert await ForwardStore(Broken()).record(**kw()) is False


async def test_name_none_is_unknown():
    s = ForwardStore(AsyncMongoMockClient()["t"])
    assert await s.record(**{**kw(), "name": None})
    assert (await s.list())[0]["name"] == "unknown"


async def test_due_and_set_outcome():
    s = ForwardStore(AsyncMongoMockClient()["t"])
    await s.record(**kw())
    await s.record(**{**kw(), "symbol": "INFY", "intraday": True, "horizon_days": 0})
    assert [r["symbol"] for r in await s.due(NOW)] == ["INFY"]
    later = datetime(2026, 11, 2, tzinfo=timezone.utc)
    due = await s.due(later)
    assert len(due) == 2
    await s.set_outcome(due[0]["_id"], {"net": 0.01, "nifty": 0.0, "excess": 0.01, "won": True}, later)
    await s.set_outcome(due[1]["_id"], {"void": True}, later)
    assert await s.due(later) == []
    assert len(await s.scored()) == 1
    assert len(await s.scored("news")) == 0
