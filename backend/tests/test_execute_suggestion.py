from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.engine.persistence import LedgerStore
from backend.suggestions.service import execute_suggestion

NOW = datetime(2024, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def ledger():
    mongo = AsyncMongoMockClient()["test_db"]
    return LedgerStore(mongo, user_id="alice")


def _option_suggestion() -> dict:
    return {
        "id": "s1", "symbol": "RELIANCE24DEC2800PE", "side": "SELL", "mode": "LONGTERM",
        "quantity": 250.0,
        "option_contract": {
            "strike": 2760.0, "expiry": "2024-12-26T00:00:00", "option_type": "PE",
            "lot_size": 250, "premium_estimate": 45.0, "margin_estimate": 82800.0,
            "underlying_spot": 2900.0,
        },
    }


@pytest.mark.asyncio
async def test_approving_an_option_suggestion_opens_a_short_position(ledger):
    order = await execute_suggestion(_option_suggestion(), ledger, price=45.0, now=NOW)

    assert order.symbol == "RELIANCE24DEC2800PE"
    assert order.product == "NRML"

    positions = await ledger.get_open_positions()
    position = positions["RELIANCE24DEC2800PE"]
    assert position.quantity == -250.0  # short: wrote the put
    assert position.avg_price == 45.0


@pytest.mark.asyncio
async def test_equity_suggestions_are_unaffected(ledger):
    suggestion = {
        "id": "s2", "symbol": "RELIANCE", "side": "BUY", "mode": "LONGTERM",
        "quantity": 10.0, "option_contract": None,
    }
    order = await execute_suggestion(suggestion, ledger, price=100.0, now=NOW)
    assert order.product == "CNC"


@pytest.mark.asyncio
async def test_the_trade_remembers_why_it_was_taken(ledger):
    suggestion = {
        "id": "s3", "symbol": "RELIANCE", "side": "BUY", "mode": "LONGTERM",
        "quantity": 10.0, "option_contract": None, "strength": 0.6,
        "reason_codes": ["macd_cross"], "score": {"rule": 0.6, "ai": 0.1, "final": 0.6},
    }
    await execute_suggestion(suggestion, ledger, price=100.0, now=NOW)
    trade = await ledger.trades.find_one({"symbol": "RELIANCE"})
    assert trade["context"] == {
        "strength": 0.6, "reason_codes": ["macd_cross"], "score": {"rule": 0.6, "ai": 0.1, "final": 0.6},
    }
