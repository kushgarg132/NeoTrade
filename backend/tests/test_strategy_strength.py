"""Signal-graded strength: a better setup scores higher, unknown data is
neutral, and no graded strength can fall under the rule floor."""

import math

from backend.scoring.composite import RULE_FLOOR
from backend.strategies.strength import graded, ramp, sma


def test_ramp_is_clamped_linear_and_neutral_on_missing_data():
    assert ramp(1.5, 1.5, 3.0) == 0.0
    assert ramp(2.25, 1.5, 3.0) == 0.5
    assert ramp(9.0, 1.5, 3.0) == 1.0
    assert ramp(-1.0, 0.0, 1.0) == 0.0
    assert ramp(None, 0.0, 1.0) == 0.5
    assert ramp(math.nan, 0.0, 1.0) == 0.5
    # A step (start == full): above/at is 1, below is 0 -- used for "trend up?"
    assert ramp(5.0, 0.0, 0.0) == 1.0
    assert ramp(-5.0, 0.0, 0.0) == 0.0


def test_graded_maps_mean_quality_onto_the_range():
    assert graded(0.5, 0.9, 0.0, 0.0) == 0.5
    assert graded(0.5, 0.9, 1.0, 1.0) == 0.9
    assert graded(0.55, 0.95, 1.0, 0.5, 0.0) == 0.75


def test_a_better_breakout_scores_higher():
    weak = graded(0.55, 0.95, ramp(1.6, 1.5, 3.0), ramp(0.1, 0.0, 1.0), ramp(-1.0, 0.0, 0.0))
    strong = graded(0.55, 0.95, ramp(3.2, 1.5, 3.0), ramp(0.9, 0.0, 1.0), ramp(5.0, 0.0, 0.0))
    assert weak < 0.62 < 0.9 < strong


def test_every_graded_range_floor_clears_the_rule_floor():
    for low in (0.55, 0.5, 0.5):  # breakout, MACD, mean reversion
        assert low > RULE_FLOOR


def test_sma_needs_enough_history():
    assert sma([1.0, 2.0, 3.0], 3) == 2.0
    assert sma([1.0, 2.0], 3) is None
