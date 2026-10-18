"""Pure-function tests for backend/data/fundamentals/scores.py -- no network,
constructed FundamentalSnapshot fixtures only."""

from backend.data.fundamentals.scores import piotroski_lite_score, quality_score
from backend.data.fundamentals.protocols import FundamentalSnapshot


def _snapshot(**overrides) -> FundamentalSnapshot:
    defaults = dict(
        symbol="TEST",
        pe_ratio=None,
        return_on_equity=None,
        return_on_assets=None,
        debt_to_equity=None,
        revenue_growth=None,
        earnings_yield=None,
    )
    defaults.update(overrides)
    return FundamentalSnapshot(**defaults)


def test_piotroski_lite_full_data_all_pass():
    snap = _snapshot(
        return_on_equity=0.20, return_on_assets=0.10, revenue_growth=0.15,
        debt_to_equity=0.5, earnings_yield=0.08,
    )
    assert piotroski_lite_score(snap) == 5


def test_piotroski_lite_partial_missing_scores_zero_for_unknown():
    snap = _snapshot(return_on_equity=0.20, return_on_assets=None, revenue_growth=0.05)
    # ROE pass, ROA unknown (0), revenue_growth pass, debt_to_equity unknown (0),
    # earnings_yield unknown (0)
    assert piotroski_lite_score(snap) == 2


def test_piotroski_lite_all_negative_or_zero_scores_zero():
    snap = _snapshot(
        return_on_equity=-0.1, return_on_assets=-0.05, revenue_growth=-0.02,
        debt_to_equity=3.0, earnings_yield=-0.01,
    )
    assert piotroski_lite_score(snap) == 0


def test_piotroski_lite_debt_to_equity_at_threshold_does_not_pass():
    snap = _snapshot(debt_to_equity=2.0)
    assert piotroski_lite_score(snap) == 0

    snap_below = _snapshot(debt_to_equity=1.999)
    assert piotroski_lite_score(snap_below) == 1


def test_quality_score_full_data_is_bounded_and_high():
    snap = _snapshot(
        return_on_equity=0.20, return_on_assets=0.10, revenue_growth=0.15,
        debt_to_equity=0.5, earnings_yield=0.12,
    )
    score = quality_score(snap)
    assert 0.0 <= score <= 1.0
    # piotroski_lite=5/5=1.0, cheapness capped at 1.0 (earnings_yield 0.12 > cap 0.10)
    assert score == 1.0


def test_quality_score_partial_data_is_between_zero_and_one():
    snap = _snapshot(return_on_equity=0.20, earnings_yield=0.05)
    score = quality_score(snap)
    # piotroski_lite = 2/5 = 0.4 (ROE + earnings_yield>0), cheapness = 0.05/0.10 = 0.5
    assert score == 0.7 * 0.4 + 0.3 * 0.5
    assert 0.0 <= score <= 1.0


def test_quality_score_all_negative_or_missing_is_zero():
    snap = _snapshot(
        return_on_equity=-0.1, return_on_assets=-0.05, revenue_growth=-0.02,
        debt_to_equity=5.0, earnings_yield=None,
    )
    assert quality_score(snap) == 0.0


def test_quality_score_never_raises_on_all_none():
    snap = _snapshot()
    assert quality_score(snap) == 0.0
    assert piotroski_lite_score(snap) == 0
