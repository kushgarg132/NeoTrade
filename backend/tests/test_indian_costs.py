"""Hand-computed expected values for the Indian brokerage/tax cost model
(backend.engine.execution.costs.calculate_indian_costs). See that module's
docstring for the rates/sources used.
"""

import pytest

from backend.core.models import Side
from backend.engine.execution.costs import calculate_indian_costs


def test_buy_cnc_small_turnover():
    # turnover = 100 * 100 = 10,000
    # brokerage = min(20, 10000*0.0003=3.0) = 3.0
    # stt (CNC, buy side too) = 10000*0.001 = 10.0
    # exchange = 10000*0.0000297 = 0.297
    # sebi = 10000*10/1e7 = 0.01
    # stamp (buy side) = 10000*0.00015 = 1.5
    # gst = 0.18*(3.0+0.297+0.01) = 0.59526
    # total = 3.0+10.0+0.297+0.01+1.5+0.59526 = 15.40226 -> 15.40
    cost = calculate_indian_costs(price=100.0, quantity=100.0, side=Side.BUY, product="CNC")
    assert cost == pytest.approx(15.40, abs=0.01)


def test_sell_cnc_small_turnover():
    # same turnover, sell side: no stamp duty, stt still both-sides for CNC
    # total = 3.0+10.0+0.297+0.01+0+0.59526 = 13.90226 -> 13.90
    cost = calculate_indian_costs(price=100.0, quantity=100.0, side=Side.SELL, product="CNC")
    assert cost == pytest.approx(13.90, abs=0.01)


def test_buy_mis_small_turnover():
    # MIS: no STT on buy side; intraday stamp duty is 0.003% (delivery's is 0.015%).
    # total = 3.0+0+0.297+0.01+0.3+0.59526 = 4.20226 -> 4.20
    cost = calculate_indian_costs(price=100.0, quantity=100.0, side=Side.BUY, product="MIS")
    assert cost == pytest.approx(4.20, abs=0.01)


def test_sell_mis_small_turnover():
    # MIS: STT 0.025% on sell side only = 10000*0.00025 = 2.5
    # total = 3.0+2.5+0.297+0.01+0+0.59526 = 6.40226 -> 6.40
    cost = calculate_indian_costs(price=100.0, quantity=100.0, side=Side.SELL, product="MIS")
    assert cost == pytest.approx(6.40, abs=0.01)


def test_brokerage_caps_at_flat_20_for_large_turnover():
    # turnover = 1000 * 100 = 100,000 -> 0.03% would be 30, so flat 20 applies.
    # stt (CNC both sides) = 100000*0.001 = 100
    # exchange = 100000*0.0000297 = 2.97
    # sebi = 100000*10/1e7 = 0.1
    # stamp (buy) = 100000*0.00015 = 15
    # gst = 0.18*(20+2.97+0.1) = 4.1526
    # total = 20+100+2.97+0.1+15+4.1526 = 142.2226 -> 142.22
    cost = calculate_indian_costs(price=1000.0, quantity=100.0, side=Side.BUY, product="CNC")
    assert cost == pytest.approx(142.22, abs=0.01)
