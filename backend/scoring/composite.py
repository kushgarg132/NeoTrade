"""Deterministic composite scoring with a structurally-capped AI weight.

`RiskAgent` (backend/components/risk/agent.py) used to blend confidence and
alignment into a single ad hoc `final_score` inline with position sizing, with
no enforced ceiling on how much AI sentiment could move the number. This
module pulls scoring out on its own and makes the AI weight impossible to
exceed AI_CAP regardless of caller input -- see CompositeScore.__post_init__.
"""

from dataclasses import dataclass
from typing import Optional

from backend.core.models import Intent, Side

AI_CAP = 0.30
RULE_FLOOR = 0.45  # rule_score below this: the trade is dead regardless of AI


@dataclass(frozen=True)
class CompositeScore:
    rule_score: float   # 0..1
    ai_score: float     # -1..1 (e.g. sentiment_score)
    ai_weight: float = AI_CAP

    def __post_init__(self):
        object.__setattr__(self, "ai_weight", max(0.0, min(self.ai_weight, AI_CAP)))
        if not (0.0 <= self.rule_score <= 1.0):
            raise ValueError(f"rule_score out of range: {self.rule_score}")
        if not (-1.0 <= self.ai_score <= 1.0):
            raise ValueError(f"ai_score out of range: {self.ai_score}")

    @property
    def final(self) -> float:
        return (1 - self.ai_weight) * self.rule_score + self.ai_weight * ((self.ai_score + 1) / 2)


def is_bearish(intent: Intent) -> bool:
    """Whether the trade wins when the stock falls: an equity sell, or a
    bought put. Selling a put (CSP) and buying a call win when it rises."""
    if intent.option_flavor is None:
        return intent.side == Side.SELL
    return intent.option_flavor == "LONG_PUT"


def score_intent(intent: Intent, ai_sentiment: Optional[float]) -> Optional[CompositeScore]:
    """Returns None if the rule floor isn't met -- AI cannot rescue a trade the
    rules didn't already support. rule_score comes from intent.strength (already
    0..1 per Task 2's Intent validation).

    `ai_sentiment` is news sentiment about the stock (positive = good news);
    it is turned to face the trade, so good news supports a bullish trade and
    argues against a bearish one."""
    if intent.strength < RULE_FLOOR:
        return None
    sentiment = ai_sentiment or 0.0
    return CompositeScore(rule_score=intent.strength, ai_score=-sentiment if is_bearish(intent) else sentiment)
