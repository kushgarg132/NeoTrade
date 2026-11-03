"""After-tax figures for the factor backtests: FIFO lots, set-off, carry-forward, and the curve."""

from datetime import date

import pandas as pd
import pytest

from backend.factor import after_tax
from backend.factor import backtest
from backend.factor.model import Params
from backend.mine.tax import LTCG_EXEMPTION


def test_a_sale_inside_a_year_is_short_and_over_a_year_is_long():
    fills = [(date(2022, 1, 3), "A", "BUY", 10, 100.0, 0.0), (date(2022, 6, 1), "A", "SELL", 4, 150.0, 0.0),
             (date(2023, 2, 1), "A", "SELL", 6, 200.0, 0.0)]
    sales, open_lots = after_tax.realise(fills)
    assert sales == [(date(2022, 6, 1), 200.0, False), (date(2023, 2, 1), 600.0, True)] and open_lots == {}


def test_lots_are_first_in_first_out_and_charges_reduce_the_gain():
    fills = [(date(2022, 1, 3), "A", "BUY", 5, 100.0, 5.0), (date(2022, 2, 1), "A", "BUY", 5, 200.0, 0.0),
             (date(2022, 3, 1), "A", "SELL", 7, 210.0, 7.0)]
    sales, open_lots = after_tax.realise(fills)
    # 5 at 100 and 2 at 200, less both legs' charges (5 on the buy, all on those shares; 7 on the sell).
    assert sales == [(date(2022, 3, 1), pytest.approx(5 * 110 + 2 * 10 - 5 - 7), False)]
    assert open_lots == {"A": [(date(2022, 2, 1), 3.0, 200.0)]}


def test_tax_by_fy_rates_and_exemption():
    sales = [(date(2023, 5, 1), 1000.0, False), (date(2023, 6, 1), LTCG_EXEMPTION + 1000.0, True)]
    assert after_tax.tax_by_fy(sales) == {2023: pytest.approx(200.0 + 125.0)}


def test_a_short_loss_offsets_long_gains_and_a_long_loss_only_long():
    assert after_tax.tax_by_fy([(date(2023, 5, 1), -2000.0, False), (date(2023, 6, 1), LTCG_EXEMPTION + 3000.0, True)]) == {
        2023: pytest.approx(125.0)}
    assert after_tax.tax_by_fy([(date(2023, 5, 1), 1000.0, False), (date(2023, 6, 1), -5000.0, True)]) == {2023: pytest.approx(200.0)}


def test_losses_carry_forward_and_stay_in_their_kind():
    sales = [(date(2023, 5, 1), -1000.0, False), (date(2024, 5, 1), 1500.0, False)]
    assert after_tax.tax_by_fy(sales) == {2023: 0.0, 2024: pytest.approx(100.0)}
    sales = [(date(2023, 5, 1), -1000.0, True), (date(2024, 5, 1), 1500.0, False)]
    assert after_tax.tax_by_fy(sales) == {2023: 0.0, 2024: pytest.approx(300.0)}


def test_a_fy_starts_in_april():
    assert after_tax.tax_by_fy([(date(2024, 3, 31), 100.0, False), (date(2024, 4, 1), 100.0, False)]) == {
        2023: pytest.approx(20.0), 2024: pytest.approx(20.0)}


def test_the_curve_pays_each_year_tax_after_the_fy_ends_and_compounds_the_loss():
    days = pd.bdate_range("2023-01-02", "2025-06-30")
    equity = pd.Series(100.0, index=days)
    curve = after_tax.after_tax_curve(equity, {2023: 10.0})
    assert curve.loc["2024-03-29"] == 100.0  # FY 2023-24 is still open
    assert curve.loc["2024-04-01"] == pytest.approx(90.0) and curve.iloc[-1] == pytest.approx(90.0)
    grown = after_tax.after_tax_curve(equity * 2, {2023: 10.0})
    assert grown.iloc[-1] == pytest.approx(200 * 0.95)  # the tax is a share of the book that day


def test_the_backtest_records_fills_and_cash_interest():
    days = pd.bdate_range("2020-01-01", periods=520)
    closes = pd.DataFrame({"A": [100 + i * 0.1 for i in range(520)], "B": [100 + i * 0.05 for i in range(520)]}, index=days)
    params = Params(momentum_weight=1.0, top_n=1, buffer=1, target_vol=None, rebalance="monthly", weighting="equal")
    result = backtest.simulate(closes, closes["A"], params, days[0], days[-1])
    assert result.fills and result.fills[0][2] == "BUY" and result.fills[0][1] in ("A", "B")
    assert sum(amount for _, amount in result.interest) > 0
