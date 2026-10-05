"""A restart must not forget open intraday positions, and one worker's
startup must not stop another worker's live runs. On 2026-10-05 six of seven
intraday runs were orphaned by deploys; each started from an empty portfolio,
16 trades were left open, and CONCOR was bought across five runs (66 shares)
against a Rs 5,000 per-stock cap."""

from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.adopt import adopt_intraday, close_stale
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.runs import BOOT_ID, RunStore

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=IST)


def _trade(symbol, side, qty, price, entry, strategy="vwap_reversion", mode="INTRADAY", status="OPEN"):
    return {"id": f"t-{symbol}", "user_id": "alice", "symbol": symbol, "side": side, "quantity": qty,
            "entry_price": price, "entry_at": entry, "mode": mode, "status": status, "strategy": strategy,
            "venue": "paper"}


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


async def test_todays_open_intraday_trades_are_adopted_with_their_owner(db):
    await db["paper_trades"].insert_many([
        _trade("CONCOR", "BUY", 11, 436.85, datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)),
        _trade("ASTRAL", "SELL", 3, 1351.2, datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc), strategy="orb_breakout"),
        _trade("ITC", "BUY", 5, 400.0, datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc), mode="LONGTERM"),
        _trade("OLD", "BUY", 7, 100.0, datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)),
    ])
    positions, holders, stale = await adopt_intraday(db, "alice", NOW)
    assert {s: (p.quantity, p.avg_price) for s, p in positions.items()} == {"CONCOR": (11, 436.85), "ASTRAL": (-3, 1351.2)}
    assert holders == {"CONCOR": "vwap_reversion", "ASTRAL": "orb_breakout"}
    assert [t["symbol"] for t in stale] == ["OLD"]


async def test_stale_intraday_trades_are_closed_at_their_mark(db):
    ledger = LedgerStore(db, user_id="alice")
    from backend.suggestions.service import execute_suggestion
    await execute_suggestion({"symbol": "OLD", "side": "BUY", "quantity": 7, "mode": "INTRADAY"}, ledger, 100.0)
    stale = await db["paper_trades"].find({"user_id": "alice", "status": "OPEN"}).to_list(10)

    async def mark(symbol):
        return 104.0

    closed = await close_stale(ledger, stale, mark, NOW)
    assert closed == 1
    trade = await db["paper_trades"].find_one({"user_id": "alice", "symbol": "OLD"})
    assert trade["status"] == "CLOSED" and trade["exit_price"] == 104.0


async def test_a_stale_trade_without_a_price_stays_for_the_next_pass(db):
    ledger = LedgerStore(db, user_id="alice")

    async def no_price(symbol):
        raise RuntimeError("no quote")

    stale = [_trade("OLD", "BUY", 7, 100.0, datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc))]
    assert await close_stale(ledger, stale, no_price, NOW) == 0


class _Redis:
    def __init__(self, alive):
        self.alive = set(alive)

    async def exists(self, key):
        return 1 if key in self.alive else 0


async def test_only_runs_whose_worker_is_gone_are_orphaned(db):
    runs = RunStore(db)
    await runs.create("mine", "alice", "INTRADAY", ["X"], {})          # this worker: alive
    await db["trading_runs"].insert_one({"run_id": "other", "status": "RUNNING", "boot_id": "worker-b"})
    await db["trading_runs"].insert_one({"run_id": "dead", "status": "RUNNING", "boot_id": "worker-gone"})
    await db["trading_runs"].insert_one({"run_id": "legacy", "status": "RUNNING"})  # before boot ids
    assert (await runs.get("mine"))["boot_id"] == BOOT_ID

    closed = await runs.close_orphaned(_Redis({f"worker:alive:{BOOT_ID}", "worker:alive:worker-b"}))

    assert closed == 2
    status = {r["run_id"]: r["status"] async for r in db["trading_runs"].find({})}
    assert status == {"mine": "RUNNING", "other": "RUNNING", "dead": "STOPPED", "legacy": "STOPPED"}


async def test_several_open_trades_on_one_stock_are_netted(db):
    """Runs that started empty opened a fresh trade for a stock already held,
    so one stock can carry several open intraday trades: adoption nets them."""
    t = datetime(2026, 10, 5, 6, 20, tzinfo=timezone.utc)
    await db["paper_trades"].insert_many([
        {**_trade("CONCOR", "BUY", 22, 440.0, t), "id": "c1"},
        {**_trade("CONCOR", "BUY", 11, 435.5, t), "id": "c2"},
        {**_trade("ASTRAL", "SELL", 3, 1351.2, t), "id": "a1"},
        {**_trade("ASTRAL", "BUY", 3, 1357.0, t), "id": "a2"},
    ])
    positions, holders, _ = await adopt_intraday(db, "alice", NOW)
    assert positions["CONCOR"].quantity == 33
    assert round(positions["CONCOR"].avg_price, 2) == round((22 * 440.0 + 11 * 435.5) / 33, 2)
    assert "ASTRAL" not in positions and "ASTRAL" not in holders  # nets to flat
