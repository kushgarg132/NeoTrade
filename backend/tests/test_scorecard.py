"""The paper scorecard is what a strategy is judged on before real money:
day by day and per strategy, always net of charges."""

from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.analytics import _max_drawdown, _profit_factor, compute_scorecard
from backend.engine.persistence import LedgerStore
from backend.routers.analytics import nifty_return


def _trade(day, pnl, costs, strategy="vwap_reversion", venue="paper", hour=5):
    exit_at = datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)  # 10:30 IST
    return {"user_id": "alice", "id": f"{strategy}-{day}-{pnl}", "symbol": "SBIN", "status": "CLOSED",
            "entry_at": exit_at, "exit_at": exit_at, "realized_pnl": pnl, "costs": costs,
            "quantity": 1, "entry_price": 1, "strategy": strategy, "venue": venue}


@pytest.fixture
def ledger():
    db = AsyncMongoMockClient()["test_db"]
    return LedgerStore(db, user_id="alice")


def test_profit_factor_and_drawdown():
    assert _profit_factor([300, -100, 100, -100]) == pytest.approx(2.0)
    assert _profit_factor([100, 50]) is None  # no losses: undefined, not infinite
    assert _profit_factor([]) is None
    assert _max_drawdown([100, -50, -80, 200, -30]) == pytest.approx(130)
    assert _max_drawdown([-40, -10]) == pytest.approx(50)


@pytest.mark.asyncio
async def test_scorecard_is_net_of_charges_by_day_and_strategy(ledger):
    await ledger.trades.insert_many([
        _trade(22, 1000, 50),
        _trade(22, -400, 40, strategy="orb_breakout"),
        _trade(23, -700, 60),
        _trade(24, 500, 30, strategy="orb_breakout"),
        _trade(24, 9999, 0, venue="live"),  # live never counts toward paper
    ])

    card = await compute_scorecard(ledger, "paper", account_size=100_000)

    assert [(d["day"], round(d["pnl"], 2), d["trades"]) for d in card["days"]] == [
        ("2026-09-22", 510.0, 2), ("2026-09-23", -760.0, 1), ("2026-09-24", 470.0, 1),
    ]
    totals = card["totals"]
    assert totals["net"] == pytest.approx(220.0)
    assert totals["costs"] == pytest.approx(180.0)
    assert totals["trades"] == 4 and totals["wins"] == 2
    assert totals["profit_factor"] == pytest.approx((950 + 470) / (440 + 760))
    assert totals["max_drawdown"] == pytest.approx(760.0)  # on the daily running total
    assert totals["max_drawdown_pct"] == pytest.approx(0.76)
    assert totals["return_pct"] == pytest.approx(0.22)
    assert totals["trading_days"] == 3 and totals["winning_days"] == 2
    assert totals["best_day"]["day"] == "2026-09-22" and totals["worst_day"]["day"] == "2026-09-23"

    by_name = {s["strategy"]: s for s in card["strategies"]}
    assert by_name["vwap_reversion"]["net"] == pytest.approx(190.0)
    assert by_name["orb_breakout"]["net"] == pytest.approx(30.0)
    assert by_name["orb_breakout"]["win_rate"] == pytest.approx(0.5)
    assert card["strategies"][0]["strategy"] == "vwap_reversion"  # best first


@pytest.mark.asyncio
async def test_empty_scorecard(ledger):
    card = await compute_scorecard(ledger, "paper", account_size=100_000)
    assert card["days"] == [] and card["strategies"] == []
    assert card["totals"]["trades"] == 0 and card["totals"]["first_day"] is None


@pytest.mark.asyncio
async def test_trades_without_a_strategy_are_grouped_not_dropped(ledger):
    await ledger.trades.insert_one({**_trade(22, 100, 10), "strategy": None})
    card = await compute_scorecard(ledger, "paper", account_size=100_000)
    assert card["strategies"][0]["strategy"] == "unattributed"


def test_nifty_return_measures_from_the_close_before_the_first_day():
    points = [{"date": "2026-09-21", "close": 100.0}, {"date": "2026-09-22", "close": 101.0},
              {"date": "2026-09-24", "close": 105.0}]
    assert nifty_return(points, "2026-09-22") == pytest.approx(5.0)
    assert nifty_return(points, "2026-09-01") is None


@pytest.mark.asyncio
async def test_a_new_trade_records_the_strategy_that_opened_it(ledger):
    from backend.core.models import Fill, Order, Position, Side

    await ledger.record_order(Order(id="o1", symbol="SBIN", side=Side.BUY, quantity=1, order_type="MARKET",
                                    limit_price=None, strategy_name="orb_breakout"))
    fill = Fill(order_id="o1", symbol="SBIN", side=Side.BUY, quantity=1, price=800.0,
                timestamp=datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc))
    await ledger.on_fill(fill, 0.0, Position(symbol="SBIN", quantity=1, avg_price=800.0))

    (trade,) = await ledger.get_trades()
    assert trade["strategy"] == "orb_breakout"
