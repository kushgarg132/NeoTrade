"""The factor book on paper: built from its own capital, respects the avoid
list, sits in cash when risk-off, rebalances once a month, and books every
trade through the paper ledger."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from mongomock_motor import AsyncMongoMockClient

from backend.factor import paper


def _load(market_trend=0.001):
    def load():
        rng = np.random.default_rng(2)
        idx = pd.bdate_range("2024-01-01", periods=400)
        closes = pd.DataFrame({
            f"S{i}": 100 * np.exp(np.cumsum(0.0005 * (i % 7) + 0.01 * rng.standard_normal(400)))
            for i in range(30)
        }, index=idx)
        market = pd.Series(100 * np.exp(np.cumsum(np.full(400, market_trend))), index=idx)
        return closes, market
    return load


async def _marks(db, symbols):
    return {s: 100.0 for s in symbols}


NOW = datetime(2026, 10, 5, 3, 50, tzinfo=timezone.utc)


async def test_first_rebalance_builds_the_book_from_its_own_capital():
    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_one({"user_id": "alice", "account_size": 10000.0})
    await db["user_profiles"].insert_one({"_id": "alice", "user_id": "alice", "avoid": ["S6"]})

    summary = await paper.rebalance(db, "alice", now=NOW, marks_fn=_marks, load=_load())

    book = await paper.FactorBookStore(db).get("alice")
    assert summary["bought"] and not summary["sold"]
    assert "S6" not in book["shares"]  # avoid list
    assert 0 < summary["invested"] <= 300_000  # its own ₹3 lakh, not the ₹10k account
    assert 299_000 < summary["equity"] < 300_000  # charges came out of the book
    trades = await db["paper_trades"].find({"user_id": "alice"}).to_list(None)
    assert trades and all(t["strategy"] == paper.STRATEGY for t in trades)
    assert not await paper.due(db, "alice", NOW)
    assert await paper.due(db, "alice", datetime(2026, 11, 2, tzinfo=timezone.utc))


async def test_a_downtrend_sells_everything_into_the_risk_off_sleeve():
    db = AsyncMongoMockClient()["test_db"]
    await paper.rebalance(db, "alice", now=NOW, marks_fn=_marks, load=_load())
    later = datetime(2026, 11, 2, 3, 50, tzinfo=timezone.utc)

    summary = await paper.rebalance(db, "alice", now=later, marks_fn=_marks, load=_load(market_trend=-0.001))

    book = await paper.FactorBookStore(db).get("alice")
    assert summary["exposure"] == 0 and summary["sold"] and book["shares"] == {}
    assert book["cash"] > 299_000  # idle cash accrued the risk-off yield for the month
    assert "risk-off" in paper.summary_text(summary)
