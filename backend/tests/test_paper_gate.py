"""The paper gate: live routing needs a paper record in the user's own
account on top of a passing backtest."""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.risk.paper_gate import paper_record, paper_records

START = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)


def _trades(pnls, costs=20.0, days=None):
    return [
        {"exit_at": START + timedelta(days=(i if days is None else i % days)),
         "realized_pnl": pnl, "costs": costs, "status": "CLOSED"}
        for i, pnl in enumerate(pnls)
    ]


def _failed(record):
    return {c["rule"] for c in record["checks"] if not c["ok"]}


def test_a_solid_record_passes():
    record = paper_record(_trades([1000.0, 1000.0, -500.0] * 10), 1_000_000.0)
    assert record["passed"], record


def test_too_few_days_and_trades():
    record = paper_record(_trades([1000.0] * 12, days=4), 1_000_000.0)
    assert _failed(record) == {"days", "trades"}
    days = next(c for c in record["checks"] if c["rule"] == "days")
    assert (days["need"], days["have"]) == (20, 4)


def test_charges_can_turn_a_gross_win_into_a_fail():
    # +10 gross per trade, 20 in charges: a loser net.
    record = paper_record(_trades([10.0] * 30), 1_000_000.0)
    assert {"net", "profit_factor"} <= _failed(record)


def test_drawdown_over_five_percent_of_account_fails():
    pnls = [2000.0] * 25 + [-12_000.0] * 5 + [20_000.0]
    record = paper_record(_trades(pnls), 1_000_000.0)
    assert "max_drawdown_pct" in _failed(record)


def test_no_trades_fails_every_rule_but_drawdown():
    assert _failed(paper_record([], 1_000_000.0)) == {"days", "trades", "net", "profit_factor"}


@pytest.mark.asyncio
async def test_records_count_only_this_users_closed_paper_trades():
    db = AsyncMongoMockClient()["test_db"]
    good = [{**t, "user_id": "u1", "strategy": "vwap_reversion", "venue": "paper"}
            for t in _trades([1000.0, 1000.0, -500.0] * 10)]
    await db["paper_trades"].insert_many([
        *good,
        {**good[0], "_id": "live", "venue": "live", "realized_pnl": -99_999.0},
        {**good[0], "_id": "other", "user_id": "u2", "realized_pnl": -99_999.0},
        {**good[0], "_id": "open", "status": "OPEN", "realized_pnl": -99_999.0},
    ])
    records = await paper_records(db, "u1", ["vwap_reversion", "orb_breakout"], 1_000_000.0)
    assert records["vwap_reversion"]["passed"]
    assert not records["orb_breakout"]["passed"]
