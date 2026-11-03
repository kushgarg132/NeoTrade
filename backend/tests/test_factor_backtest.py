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


def _membership_prices():
    """Two strong stocks and a weak one over two years of trading days."""
    days = pd.bdate_range("2020-01-01", periods=520)
    growth = {"STAR": 1.004, "GOOD": 1.002, "WEAK": 1.0002}
    return pd.DataFrame({s: 100 * g ** np.arange(len(days)) for s, g in growth.items()}, index=days)


def _rotation(top_n=1):
    return Params(momentum_weight=1.0, top_n=top_n, buffer=top_n, target_vol=None, rebalance="monthly", weighting="equal")


def test_a_stock_outside_the_index_is_never_bought():
    closes = _membership_prices()
    member = pd.DataFrame(True, index=closes.index, columns=closes.columns)
    member["STAR"] = False
    market = closes["WEAK"]
    held = {s for _, book, _ in backtest.simulate(closes, market, _rotation(), closes.index[0], closes.index[-1], member=member).books for s in book}
    assert "STAR" not in held and "GOOD" in held
    free = {s for _, book, _ in backtest.simulate(closes, market, _rotation(), closes.index[0], closes.index[-1]).books for s in book}
    assert "STAR" in free


def test_a_holding_that_leaves_the_index_is_sold():
    closes = _membership_prices()
    member = pd.DataFrame(True, index=closes.index, columns=closes.columns)
    member.loc[closes.index[450]:, "STAR"] = False
    books = backtest.simulate(closes, closes["WEAK"], _rotation(), closes.index[0], closes.index[-1], member=member).books
    assert any("STAR" in book for day, book, _ in books if day < closes.index[450])
    assert all("STAR" not in book for day, book, _ in books if day >= closes.index[450])


def test_walk_forward_passes_membership_to_every_variant():
    from backend.factor import validate

    closes = _membership_prices()
    member = pd.DataFrame(True, index=closes.index, columns=closes.columns)
    member["STAR"] = False
    out = validate.walk_forward(closes, closes["WEAK"], closes.index[0], closes.index[-1], [_rotation()], in_sample_years=1, member=member)
    assert all("STAR" not in book for result in out.trials.values() for _, book, _ in result.books)


@pytest.mark.real_members
def test_rolled_membership_fills_the_2019_to_2023_gap_and_leaves_the_default_alone():
    from backend.forecast import members

    days = pd.DatetimeIndex(["2021-09-29", "2021-09-30", "2019-01-01"]).sort_values()
    rolled = members.mask(days, ["HINDCOPPER", "CESC", "TCS"], rolled=True)
    assert rolled["HINDCOPPER"].tolist() == [False, False, True]
    assert rolled["CESC"].tolist()[1:] == [True, False]  # NSE's 2021-08-23 release took it out from 30 September
    assert rolled["TCS"].all()
    plain = members.mask(days, ["HINDCOPPER"])
    assert not plain["HINDCOPPER"].any()  # the Picks study still reads only the archived lists
