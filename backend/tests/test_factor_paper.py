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
    # idle cash accrued the risk-off yield for the month; every sell paid the
    # Rs 15.93 DP charge on top of the other charges
    assert book["cash"] > 298_800
    assert "risk-off" in paper.summary_text(summary)


async def test_the_book_tracks_itself_against_the_nifty_since_it_started():
    db = AsyncMongoMockClient()["test_db"]
    await paper.rebalance(db, "alice", now=NOW, marks_fn=_marks, load=_load())
    book = await paper.FactorBookStore(db).get("alice")
    assert book["started_at"] == NOW.replace(tzinfo=None) or book["started_at"] == NOW
    assert book["start_equity"] == 300_000 and book["start_nifty"] > 0

    later = datetime(2026, 11, 2, 3, 50, tzinfo=timezone.utc)
    summary = await paper.rebalance(db, "alice", now=later, marks_fn=_marks, load=_load())
    assert "book_return" in summary and "nifty_return" in summary
    assert "vs Nifty" in paper.summary_text(summary)


# Small account: 15-20 names x 10% on Rs 25,000 left Rs 1,250 a name, so
# whole shares broke expensive stocks. Below Rs 2 lakh the book holds the top
# 8 and skips a stock whose single share costs more than its slot.

def _priced_load(prices):
    def load():
        idx = pd.bdate_range("2024-01-01", periods=400)
        rng = np.random.default_rng(5)
        closes = pd.DataFrame({
            s: p * np.exp(np.cumsum((0.004 if p > 1000 else 0.001) + 0.005 * rng.standard_normal(400)))
            for s, p in prices.items()
        }, index=idx)
        market = pd.Series(100 * np.exp(np.cumsum(np.full(400, 0.001))), index=idx)
        return closes, market
    return load


async def test_a_small_book_holds_at_most_eight_names():
    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_one({"user_id": "alice", "factor_paper_capital": 25_000.0})

    async def marks(db, symbols):
        return {s: 100.0 for s in symbols}

    await paper.rebalance(db, "alice", now=NOW, marks_fn=marks, load=_load())
    book = await paper.FactorBookStore(db).get("alice")
    assert 0 < len(book["shares"]) <= paper.SMALL_TOP_N


async def test_a_stock_dearer_than_its_slot_is_skipped():
    db = AsyncMongoMockClient()["test_db"]
    await db["user_prefs"].insert_one({"user_id": "alice", "factor_paper_capital": 25_000.0})
    prices = {f"S{i}": 100.0 for i in range(12)} | {"PRICEY": 9_000.0}  # slot ~ Rs 3,125

    async def marks(db, symbols):
        return {s: (9_000.0 if s == "PRICEY" else 100.0) for s in symbols}

    await paper.rebalance(db, "alice", now=NOW, marks_fn=marks, load=_priced_load(prices))
    shares = (await paper.FactorBookStore(db).get("alice"))["shares"]
    # PRICEY ranks first on momentum, but one share (Rs 9,000) is more than a
    # slot: it is skipped and the next-ranked name takes its place.
    assert "PRICEY" not in shares and len(shares) == paper.SMALL_TOP_N
