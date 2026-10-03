"""The chat's read tools: every one is bound to the caller and never shows
another user's data."""

from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from backend.chat.tools import read_tools


async def _seed(db):
    now = datetime.now(timezone.utc)
    for user, symbol in (("alice", "SJVN"), ("bob", "BOBCO")):
        await db["suggestions"].insert_one({
            "id": f"s-{user}", "user_id": user, "symbol": symbol, "side": "BUY", "mode": "LONGTERM",
            "status": "PENDING", "quantity": 21, "entry_ref": 57.91, "stop": 55.01, "target": 60.81,
            "score": {"final": 0.54, "rule": 0.67, "ai": 0.1}, "reason_codes": ["oversold"], "ai_thesis": "t",
            "created_at": now, "expires_at": now + timedelta(days=3),
        })
        await db["portfolio_snapshots"].insert_one({
            "user_id": user, "at": now, "totals": {"value": 100.0, "day_change": -1.0, "pnl_pct": 2.0},
            "holdings": [{"symbol": symbol, "kind": "STOCK", "value": 100.0, "pnl_pct": 2.0, "verdict": "HOLD", "reason_codes": []}],
            "plan": f"### Add\n- **{symbol}**: x", "summary": "s", "concentration": {}, "benchmark": {},
        })
        await db["journal_trades"].insert_one({
            "_id": f"{user}:kite:t1", "user_id": user, "broker": "kite", "exchange": "NSE", "symbol": symbol,
            "side": "BUY", "quantity": 1, "price": 10.0, "traded_at": now, "trade_id": "t1",
        })
        await db["user_prefs"].insert_one({"user_id": user, "daily_loss_limit": 1.0})


def _tools(db, user):
    return {t.name: t for t in read_tools(db, None, user)}


async def test_read_tools_only_see_the_callers_data():
    db = AsyncMongoMockClient()["test_db"]
    await _seed(db)
    tools = _tools(db, "alice")
    outputs = [
        await tools["get_portfolio"].ainvoke({}),
        await tools["get_journal"].ainvoke({"period": "all"}),
        await tools["get_decisions"].ainvoke({}),
        await tools["get_limits"].ainvoke({}),
        await tools["get_paper"].ainvoke({}),
    ]
    assert any("SJVN" in o for o in outputs)
    assert not any("BOBCO" in o for o in outputs)


async def test_get_decisions_lists_ids_terms_and_score():
    db = AsyncMongoMockClient()["test_db"]
    await _seed(db)
    out = await _tools(db, "alice")["get_decisions"].ainvoke({})
    for expected in ("s-alice", "SJVN", "57.91", "55.01", "60.81", "0.54"):
        assert expected in out


async def test_get_paper_reports_a_running_runs_progress():
    from backend.runs import RunStore

    db = AsyncMongoMockClient()["test_db"]
    await _seed(db)
    runs = RunStore(db)
    await runs.create("r-alice", "alice", "LONGTERM", ["SJVN"], {"origin": "manual"})
    await runs.set_progress("r-alice", {"bars": 166, "signals": 2, "orders": 1, "last_symbol": "SJVN"})
    out = await _tools(db, "alice")["get_paper"].ainvoke({})
    for expected in ("r-alice", "'bars': 166", "'signals': 2", "started_at"):
        assert expected in out or expected.replace("'", '"') in out
