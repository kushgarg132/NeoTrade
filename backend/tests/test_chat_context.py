"""The chat's day snapshot: one user's figures only, and a failing section
reported as unavailable rather than breaking the answer."""

from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.chat import context
from backend.chat.context import build_snapshot, format_snapshot, plan_names


async def _seed(db):
    now = datetime.now(timezone.utc)
    for user, symbol, limit in (("alice", "SJVN", 5000.0), ("bob", "BOBCO", 9999.0)):
        await db["suggestions"].insert_one({
            "id": f"s-{user}", "user_id": user, "symbol": symbol, "side": "BUY", "mode": "LONGTERM",
            "status": "PENDING", "score": {"final": 0.6}, "created_at": now, "expires_at": now + timedelta(days=3),
        })
        await db["user_prefs"].insert_one({"user_id": user, "daily_loss_limit": limit})


async def test_snapshot_is_scoped_to_the_user():
    db = AsyncMongoMockClient()["test_db"]
    await _seed(db)
    snap = await build_snapshot(db, None, "alice")
    assert snap["decisions"]["pending"] == 1
    assert [s["symbol"] for s in snap["decisions"]["top"]] == ["SJVN"]
    assert snap["limits"]["daily_loss_limit"] == 5000.0
    assert "BOBCO" not in format_snapshot(snap)


async def test_snapshot_marks_a_failing_section_unavailable(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    await _seed(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("no snapshot")

    monkeypatch.setattr(context, "latest_snapshot", boom)
    snap = await build_snapshot(db, None, "alice")
    assert "unavailable" in snap["portfolio"]
    assert snap["decisions"]["pending"] == 1
    assert "unavailable" in format_snapshot(snap)


def test_plan_names_reads_bold_bullets():
    plan = "### Sell or trim\n- **WIPRO**: x\n- **BDL** (y): z\n### Add\n- **HFCL** (Score 0.74): a"
    assert plan_names(plan, "sell") == ["WIPRO", "BDL"]
    assert plan_names(plan, "add") == ["HFCL"]
    assert plan_names(None, "add") == []
