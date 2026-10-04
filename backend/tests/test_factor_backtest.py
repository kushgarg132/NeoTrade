"""The factor backtest trades the day after it decides, pays costs, marks
to market, and sits in the risk-off sleeve when the market trend breaks."""

import numpy as np
import pandas as pd
import pytest

from backend.factor import backtest
from backend.factor.model import Params


def _world(days=600, market_trend=0.0005, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=days)
    closes = pd.DataFrame({
        f"S{i}": 100 * np.exp(np.cumsum(0.0004 * (i % 5) + 0.01 * rng.standard_normal(days)))
        for i in range(30)
    }, index=idx)
    market = pd.Series(100 * np.exp(np.cumsum(np.full(days, market_trend))), index=idx)
    return closes, market


def test_trades_the_day_after_deciding_and_pays_costs():
    closes, market = _world()
    start, end = closes.index[300], closes.index[-1]
    result = backtest.simulate(closes, market, Params(top_n=5, target_vol=None), start, end)
    first_decision = result.books[0][0]
    # Nothing is held (equity only grows by the cash yield) until the day after the first decision.
    before = result.equity.loc[:first_decision]
    assert (before.diff().dropna() >= 0).all()
    assert result.costs > 0 and result.traded > 0
    m = result.metrics()
    assert m["rebalances"] >= 10 and m["cost_drag"] > 0


def test_a_market_downtrend_keeps_the_money_in_the_risk_off_sleeve():
    closes, market = _world(market_trend=-0.001)
    start, end = closes.index[300], closes.index[-1]
    result = backtest.simulate(closes, market, Params(top_n=5), start, end, risk_off_yield=0.065)
    assert result.costs == 0
    years = len(result.equity) / 252  # cash earns from the first day
    assert result.equity.iloc[-1] == pytest.approx(1_000_000 * 1.065 ** years, rel=1e-6)


def test_drawdown_sees_unrealised_losses():
    idx = pd.bdate_range("2020-01-01", periods=5)
    equity = pd.Series([100.0, 120.0, 90.0, 95.0, 130.0], index=idx)
    assert backtest.performance(equity)["max_drawdown"] == pytest.approx(-0.25)


def test_rebalance_days_are_month_or_quarter_ends():
    idx = pd.bdate_range("2021-01-01", "2021-12-31")
    assert len(backtest.rebalance_days(idx, "monthly")) == 12
    assert len(backtest.rebalance_days(idx, "quarterly")) == 4
    assert pd.Timestamp("2021-03-31") in backtest.rebalance_days(idx, "quarterly")


def test_deflated_sharpe_punishes_many_trials_and_rewards_a_real_edge():
    from backend.factor.validate import deflated_sharpe

    rng = np.random.default_rng(3)
    edge = pd.Series(0.001 + 0.01 * rng.standard_normal(2500))   # daily Sharpe ~0.1 over 10 years
    noise = pd.Series(0.01 * rng.standard_normal(2500))
    assert deflated_sharpe(edge, [0.0]) > 0.95
    assert deflated_sharpe(noise, [0.0]) < 0.95
    # The same curve, picked as the best of many noisy variants, is worth less.
    many = list(0.03 * rng.standard_normal(100))
    assert deflated_sharpe(edge, many) < deflated_sharpe(edge, [0.0])


def test_walk_forward_only_counts_years_after_the_in_sample_window():
    from backend.factor.validate import walk_forward

    closes, market = _world(days=1300)
    start, end = closes.index[260], closes.index[-1]
    variants = [Params(top_n=5, buffer=8, target_vol=None), Params(top_n=8, buffer=12, target_vol=None)]
    wf = walk_forward(closes, market, start, end, variants, in_sample_years=2)
    first_year = closes.loc[start:].index[0].year
    assert min(wf.chosen) == first_year + 2
    assert wf.returns.index.min().year == first_year + 2
    assert 0.0 <= wf.dsr <= 1.0
