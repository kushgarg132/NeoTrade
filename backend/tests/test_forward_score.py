from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import scheduler
from backend.forward import score
from backend.lab.assumptions import round_trip_return

HOLIDAY = pd.Timestamp("2026-10-20")
DAYS = pd.bdate_range("2026-10-19", "2026-11-13").difference([HOLIDAY])
OPEN = [100.0 + i for i in range(len(DAYS))]
CLOSE = [101.0 + i * 1.5 for i in range(len(DAYS))]
DECIDED = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)  # 16:00 IST


def table(days=DAYS):
    n = len(days)
    return {
        "open": pd.DataFrame({"AAA": OPEN[:n]}, index=days), "close": pd.DataFrame({"AAA": CLOSE[:n]}, index=days),
        "nifty_open": pd.Series([200.0 + i for i in range(n)], index=days),
        "nifty_close": pd.Series([201.0 + i for i in range(n)], index=days),
    }


def rec(**kw):
    return {"_id": "r", "symbol": "AAA", "side": "BUY", "decided_at": DECIDED, "intraday": False,
            "ref_price": None, "horizon_days": 1, **kw}


def test_buy_enters_next_open_across_holiday_and_exits_horizon_later():
    out = score.outcome(table(), rec())
    # 10-19 decided; 10-20 holiday -> entry 10-21 (index 1), exit 10-22 (index 2)
    assert (out["entry_date"], out["exit_date"]) == ("2026-10-21", "2026-10-22")
    assert out["net"] == round_trip_return(OPEN[1], CLOSE[2])
    assert out["nifty"] == pytest.approx(203.0 / 201.0 - 1)
    assert out["excess"] == pytest.approx(out["net"] - out["nifty"]) and out["won"] == (out["net"] > 0)


def test_intraday_enters_at_ref_price_and_exits_same_day_close():
    out = score.outcome(table(), rec(intraday=True, ref_price=100.5, horizon_days=0))
    assert out["entry_date"] == out["exit_date"] == "2026-10-19"
    assert out["net"] == round_trip_return(100.5, CLOSE[0])


def test_sell_scores_the_short_side():
    out = score.outcome(table(), rec(side="SELL"))
    assert out["net"] == round_trip_return(CLOSE[2], OPEN[1])


def test_unknown_symbol_waits_then_voids_after_ten_trading_days():
    assert score.outcome(table(DAYS[:4]), rec(symbol="ZZZ")) is None
    assert score.outcome(table(), rec(symbol="ZZZ")) == {"void": "no bars"}


async def test_score_due_sets_outcomes_only_for_scorable_records():
    class Store:
        sets = []

        async def due(self, now):
            return [rec(_id="a"), rec(_id="b", symbol="ZZZ")]

        async def set_outcome(self, record_id, outcome, now):
            self.sets.append((record_id, outcome))

    assert await score.score_due(None, DECIDED, t=table(DAYS[:6]), store=Store()) == 1
    assert [i for i, _ in Store.sets] == ["a"]


async def test_scheduler_pass_survives_a_failing_forward_step(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(score, "score_due", boom)
    sent = AsyncMock(return_value=0)
    monkeypatch.setattr("backend.portfolio.digest.send_postclose", sent)
    monkeypatch.setattr("backend.learning.retune.spawn", AsyncMock())

    await scheduler.run_daily_jobs(AsyncMongoMockClient()["t"], now=datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc))

    sent.assert_awaited()


def test_sell_excess_adds_the_index_return():
    out = score.outcome(table(), rec(side="SELL"))
    assert out["excess"] == pytest.approx(out["net"] + out["nifty"])


def test_intraday_nifty_uses_ref_then_falls_back_to_day_open():
    r = rec(intraday=True, ref_price=100.5, horizon_days=0)
    assert score.outcome(table(), r)["nifty"] == pytest.approx(201.0 / 200.0 - 1)
    out = score.outcome(table(), {**r, "nifty_ref": 200.5})
    assert out["nifty"] == pytest.approx(201.0 / 200.5 - 1)


async def test_void_record_does_not_break_scorecard():
    from backend.forward.scorecard import scorecard
    from backend.forward.store import ForwardStore

    db = AsyncMongoMockClient()["v"]
    s = ForwardStore(db)
    kw = dict(source="picks", name="n", user_id="u", side="BUY", decided_at=DECIDED, intraday=False,
              ref_price=None, horizon_days=1)
    await s.record(symbol="AAA", **kw)
    await s.record(symbol="ZZZ", **kw)
    assert await score.score_due(db, datetime(2026, 11, 13, tzinfo=timezone.utc), t=table(), store=s) == 1
    assert (await db["forward_records"].find_one({"symbol": "ZZZ"}))["outcome"] == {"void": "no bars"}
    [row] = await scorecard(db)
    assert row["n"] == 1
