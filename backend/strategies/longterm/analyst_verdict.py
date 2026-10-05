"""A LONGTERM strategy whose entry signal is genuinely analyst/LLM-derived, not a technical
indicator -- the concrete substance of ROADMAP.md Phase 6's "give long-term suggestions a
genuine reasoning source". `verdicts` is precomputed by backend/ai/analyst_verdict.py's
cache-then-read shape and handed in at construction, same pattern
backend/strategies/longterm/quality_momentum.py already established: this module does NO I/O
of its own, per the project's no-I/O-in-strategies rule
(backend/tests/test_no_network_in_strategies.py).
"""

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.scoring.composite import AI_CAP, RULE_FLOOR
from backend.strategies.base import TokenResolvingStrategy
from backend.strategies.card import StrategyCard

# 1-10 scale (backend.components.shared.models.NewsArticle.impact_score's own range) -- below
# this, routine/low-consequence news shouldn't be enough to trigger a trade.
MATERIALITY_THRESHOLD = 6


class AnalystVerdictStrategy(TokenResolvingStrategy):
    """BUY when the symbol's cached analyst verdict is bullish and material. `verdicts` is a
    symbol -> {"sentiment_score", "impact_score", "label", "top_reason"} lookup for the same
    curated universe this strategy trades."""
    CARD = StrategyCard(
        style="value", regimes=["risk_on", "neutral", "risk_off"], needs=["catalyst"],
        best_when="A fresh, material analyst verdict backed by scored news.",
        avoid_when="Stale verdicts or news the market has already priced in.",
        typical_hold_minutes=22500,
    )

    def __init__(
        self,
        universe: list[str],
        symbol_for_token: dict[int, str],
        verdicts: dict[str, dict],
    ) -> None:
        super().__init__(universe, symbol_for_token)
        self.verdicts = verdicts
        self.spec = StrategySpec(
            name="analyst_verdict", mode="LONGTERM", timeframe="1d",
            warmup_bars=1, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None or symbol not in self.verdicts:
            return

        verdict = self.verdicts[symbol]
        if verdict.get("label") != "bullish" or verdict.get("impact_score", 0) < MATERIALITY_THRESHOLD:
            return

        history = ctx.history(symbol, 1)
        if not history:
            return
        current_price = history[-1].close

        # This same LLM sentiment number also flows into the ai_score channel later
        # (backend.scoring.composite.score_intent, via get_cached_sentiment's shared cache)
        # -- so the rule channel must not carry it unbounded, or AI_CAP/RULE_FLOOR do
        # nothing for this strategy's intents. Bounding to RULE_FLOOR + AI_CAP * fraction
        # keeps "clears the floor by construction" (min value is exactly RULE_FLOOR) while
        # capping how far a single verdict can push the rule-channel number.
        # The cached sentiment_score comes from an LLM call with no upstream range
        # validation -- clamp defensively so a hallucinated value can never raise out of
        # Intent's own [0, 1] strength check and take down the whole scan.
        fraction = max(0.0, min(1.0, (float(verdict.get("sentiment_score", 0.0) or 0.0) + 1) / 2))
        strength = RULE_FLOOR + AI_CAP * fraction

        reason_codes = [c for c in ("analyst_bullish_verdict", verdict.get("top_reason", "")) if c]
        ctx.submit(Intent(
            symbol=symbol, side=Side.BUY, strength=strength,
            reason_codes=reason_codes,
            stop_hint=current_price * 0.90,
            target_hint=current_price * 1.15,
        ))
