from backend.core.models import Side
from backend.engine.execution.options_costs import calculate_options_costs


def test_sell_side_costs_are_positive():
    costs = calculate_options_costs(premium=45.0, quantity=250.0, side=Side.SELL)
    assert costs > 0.0


def test_buy_side_costs_are_lower_than_sell_side_for_the_same_turnover():
    # STT applies to the sell/write side only, same convention the equity
    # model (calculate_indian_costs) already uses for intraday.
    buy_costs = calculate_options_costs(premium=45.0, quantity=250.0, side=Side.BUY)
    sell_costs = calculate_options_costs(premium=45.0, quantity=250.0, side=Side.SELL)
    assert buy_costs < sell_costs


def test_sell_side_matches_the_nse_schedule():
    # Rs 1 lakh of premium sold: 20 brokerage + 100 STT + 35.03 exchange + 0.10 SEBI
    # + 18% GST on (20 + 35.03 + 0.10).
    assert calculate_options_costs(premium=100.0, quantity=1000.0, side=Side.SELL) == round(
        20 + 100 + 35.03 + 0.10 + 0.18 * (20 + 35.03 + 0.10), 2)
    # the buy side pays 3.00 stamp duty and no STT
    assert calculate_options_costs(premium=100.0, quantity=1000.0, side=Side.BUY) == round(
        20 + 35.03 + 0.10 + 3.0 + 0.18 * (20 + 35.03 + 0.10), 2)
