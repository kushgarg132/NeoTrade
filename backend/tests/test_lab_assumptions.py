import pandas as pd
import pytest

from backend.core.models import Side
from backend.engine import backtest as engine_backtest
from backend.engine.execution.costs import calculate_indian_costs
from backend.factor import backtest as factor_backtest
from backend.forecast import study
from backend.lab.assumptions import DAILY, DEFAULT, fill_price, round_trip_return


def test_fill_price_is_adverse():
    assert fill_price(100.0, Side.BUY, DEFAULT) == pytest.approx(100.1)
    assert fill_price(100.0, Side.SELL, DEFAULT) == pytest.approx(99.9)


def test_round_trip_matches_hand_math():
    qty = 1e5 / 100.1
    charges = calculate_indian_costs(100.1, qty, Side.BUY, "CNC") + calculate_indian_costs(109.89, qty, Side.SELL, "CNC")
    assert round_trip_return(100.0, 110.0) == pytest.approx((qty * (109.89 - 100.1) - charges) / 1e5)


def test_study_net_return_uses_it():
    assert study.net_return(100.0, 110.0) == pytest.approx(round_trip_return(100.0, 110.0))


def test_factor_trade_slips_like_the_shared_fill():
    shares, result = {}, factor_backtest.Result(equity=pd.Series(dtype=float))
    cash = factor_backtest._trade(shares, 1_000_000.0, pd.Series({"A": 100.0}), pd.Series({"A": 1.0}), DAILY, result)
    price = fill_price(100.0, Side.BUY, DAILY)
    assert result.traded / shares["A"] == pytest.approx(price)
    assert cash == pytest.approx(1_000_000.0 - result.traded - result.costs)


async def test_engine_backtest_uses_default_slippage(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    def capture(**kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(engine_backtest, "SimulatedExecutionClient", capture)
    with pytest.raises(Stop):
        await engine_backtest.run_backtest([], None, [], None, None, "1m")
    assert seen["slippage_bps"] == DEFAULT.slippage_bps
