import pytest
from pydantic import ValidationError

from backend.strategies.card import StrategyCard
from backend.strategies.registry import build_default_strategies


def _all():
    return build_default_strategies(
        universe=["X"], quality_universe=["X"], quality_scores={"X": 0.6},
        analyst_verdicts={"X": {}}, option_universe=["X"],
    )


def test_every_registered_strategy_has_a_card():
    for strategy in _all():
        assert isinstance(getattr(strategy, "CARD", None), StrategyCard), strategy.spec.name


def test_card_rejects_unknown_regime():
    with pytest.raises(ValidationError):
        StrategyCard(style="breakout", regimes=["bull"], needs=[], best_when="x", avoid_when="y",
                     typical_hold_minutes=10)
