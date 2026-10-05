"""The plan's actual new long-term strategy (not a port): momentum-timed
entry on top of a fundamentals-screened universe. Universe + quality scores
are precomputed by backend/screening/universe.py::build_quality_universe and
handed in at construction -- this strategy does NO I/O of its own, per the
project's no-I/O-in-strategies rule (backend/tests/test_no_network_in_strategies.py).
"""

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.card import StrategyCard

_SMA_PERIOD = 200


class QualityMomentumStrategy(TokenResolvingStrategy):
    """BUY when price crosses above its 200-day SMA (regime filter) AND the
    symbol is in the quality-screened universe. `quality_scores` is a
    symbol -> quality_score lookup for the same universe -- used directly as
    Intent.strength."""
    CARD = StrategyCard(
        style="value", regimes=["risk_on", "neutral"], needs=[],
        best_when="Strong-fundamentals names are also leading on price.",
        avoid_when="A broad sell-off, where quality falls with everything else.",
        typical_hold_minutes=22500,
    )

    def __init__(
        self,
        universe: list[str],
        symbol_for_token: dict[int, str],
        quality_scores: dict[str, float],
    ) -> None:
        super().__init__(universe, symbol_for_token)
        self.quality_scores = quality_scores
        self.spec = StrategySpec(
            name="quality_momentum", mode="LONGTERM", timeframe="1d",
            warmup_bars=_SMA_PERIOD + 1, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None or symbol not in self.quality_scores:
            return

        history = ctx.history(symbol, self.spec.warmup_bars)
        if len(history) < self.spec.warmup_bars:
            return

        df = bars_to_dataframe(history)
        sma200 = Indicators.sma(df["close"], _SMA_PERIOD)
        current_price = df["close"].iloc[-1]
        curr_sma = sma200.iloc[-1]
        prev_price = df["close"].iloc[-2]
        prev_sma = sma200.iloc[-2]

        crossed_above = prev_price <= prev_sma and current_price > curr_sma
        if not crossed_above:
            return

        ctx.submit(Intent(
            symbol=symbol, side=Side.BUY, strength=self.quality_scores[symbol],
            reason_codes=["quality_screen_pass", "price_above_sma200"],
            stop_hint=current_price * 0.90,
            target_hint=current_price * 1.20,
        ))
