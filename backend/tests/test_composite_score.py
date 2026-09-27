"""AI sentiment must be structurally incapable of rescuing a trade the rules
didn't already support -- these tests prove the cap arithmetically, not by
convention (backend.scoring.composite)."""

import pytest

from backend.core.models import Intent, Side
from backend.scoring.composite import AI_CAP, RULE_FLOOR, CompositeScore, score_intent


def test_max_ai_score_on_zero_rule_score_cannot_cross_floor():
    """Even maximum possible AI input (ai_score=1.0) on a rule_score of 0
    cannot cross a reasonable entry threshold -- the exact scenario the brief
    requires as proof."""
    assert CompositeScore(rule_score=0.0, ai_score=1.0).final < 0.45


def test_ai_weight_is_clamped_to_cap_regardless_of_input():
    score = CompositeScore(rule_score=0.5, ai_score=0.0, ai_weight=0.99)
    assert score.ai_weight == AI_CAP


def test_ai_weight_never_negative():
    score = CompositeScore(rule_score=0.5, ai_score=0.0, ai_weight=-1.0)
    assert score.ai_weight == 0.0


def test_composite_score_is_frozen():
    score = CompositeScore(rule_score=0.5, ai_score=0.0)
    with pytest.raises(Exception):
        score.rule_score = 0.9  # type: ignore[misc]


@pytest.mark.parametrize("rule_score", [-0.01, 1.01])
def test_rejects_out_of_range_rule_score(rule_score):
    with pytest.raises(ValueError):
        CompositeScore(rule_score=rule_score, ai_score=0.0)


@pytest.mark.parametrize("ai_score", [-1.01, 1.01])
def test_rejects_out_of_range_ai_score(ai_score):
    with pytest.raises(ValueError):
        CompositeScore(rule_score=0.5, ai_score=ai_score)


@pytest.mark.parametrize("ai_sentiment", [-1.0, 0.0, 1.0])
def test_score_intent_returns_none_below_rule_floor(ai_sentiment):
    intent = Intent(
        symbol="TEST", side=Side.BUY, strength=RULE_FLOOR - 0.01, reason_codes=["r"],
    )
    assert score_intent(intent, ai_sentiment) is None


def test_score_intent_returns_score_at_or_above_floor():
    intent = Intent(symbol="TEST", side=Side.BUY, strength=RULE_FLOOR, reason_codes=["r"])
    result = score_intent(intent, 0.0)
    assert result is not None
    assert result.rule_score == RULE_FLOOR


def test_score_intent_none_ai_sentiment_treated_as_neutral():
    intent = Intent(symbol="TEST", side=Side.BUY, strength=0.8, reason_codes=["r"])
    result = score_intent(intent, None)
    assert result is not None
    assert result.ai_score == 0.0


def test_ai_sentiment_can_nudge_final_score_up_or_down():
    """The other half of the design: above the floor, AI can still move the
    needle in either direction for the same rule_score."""
    intent = Intent(symbol="TEST", side=Side.BUY, strength=0.8, reason_codes=["r"])
    bullish = score_intent(intent, 1.0)
    bearish = score_intent(intent, -1.0)
    assert bullish.final > bearish.final


@pytest.mark.parametrize("side, flavor, bearish", [
    (Side.BUY, None, False),
    (Side.SELL, None, True),
    (Side.SELL, "CSP", False),       # selling a put pays when the stock holds up
    (Side.BUY, "LONG_CALL", False),
    (Side.BUY, "LONG_PUT", True),
])
def test_good_news_supports_bullish_trades_and_argues_against_bearish_ones(side, flavor, bearish):
    intent = Intent(symbol="TEST", side=side, strength=0.8, reason_codes=["r"], option_flavor=flavor)
    good, bad = score_intent(intent, 1.0), score_intent(intent, -1.0)
    assert (good.final < bad.final) is bearish
    assert abs(good.final - bad.final) <= AI_CAP + 1e-9
