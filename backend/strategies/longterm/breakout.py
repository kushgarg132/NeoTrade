"""Ported from backend/components/quant/strategies.py::TechnicalBreakout.
Same logic, thresholds, and stop/target formulas -- structural port onto the
Strategy protocol, not a redesign.

Strength is graded 0.55..0.95 (was a flat 0.8): how far volume exceeds the
1.5x confirmation (full at 3x), how decisively price cleared resistance
(full at 1 ATR above), and whether the 200-day trend is up."""

from backend.components.quant.indicators import Indicators
from backend.components.quant.support import SupportResistance
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.strength import graded, ramp, sma
from backend.strategies.card import StrategyCard


class TechnicalBreakoutStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="breakout", regimes=["risk_on"], needs=["volume_spike"],
        best_when="A stock clears multi-week resistance on rising volume in a rising market.",
        avoid_when="A risk-off market, where breakouts fail more often than they run.",
        typical_hold_minutes=7500,
    )
    PARAMS = {"volume_mult": 1.5, "target_r": 2.0}
    GRID = {"volume_mult": [1.5, 2.0], "target_r": [1.5, 2.0, 3.0]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="technical_breakout", mode="LONGTERM", timeframe="1d",
            warmup_bars=50, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return

        history = ctx.history(symbol, self.spec.warmup_bars)
        if len(history) < self.spec.warmup_bars:
            return

        df = Indicators.calculate_all(bars_to_dataframe(history))
        current_price = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        levels = SupportResistance.identify_levels(df)
        # NOTE (bug fix, see report): the original file passed `current_price`
        # here, but get_nearest_levels only returns a level as `resistance`
        # when that level is *above* the price it's given -- so with
        # current_price, `current_price > resistance` could never be true and
        # the original strategy could never fire. Passing `prev_close` (the
        # bar the breakout happens against) is what "close above resistance"
        # actually requires; the resistance level, stop/target formulas, and
        # every threshold are otherwise unchanged from the original.
        _, resistance = SupportResistance.get_nearest_levels(prev_close, levels)

        # Breakout: close crosses above resistance with volume confirmation
        # (current volume > 1.5x its 20-bar average).
        if not resistance or not (prev_close < resistance and current_price > resistance):
            return
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        if df["volume"].iloc[-1] <= self.p["volume_mult"] * avg_vol:
            return

        sma_200 = sma([b.close for b in ctx.history(symbol, 200)], 200)
        strength = graded(
            0.55, 0.95,
            ramp(df["volume"].iloc[-1] / avg_vol, self.p["volume_mult"], 2 * self.p["volume_mult"]),
            ramp((current_price - resistance) / df["atr_14"].iloc[-1], 0.0, 1.0),
            ramp(None if sma_200 is None else current_price - sma_200, 0.0, 0.0),
        )
        ctx.submit(Intent(
            symbol=symbol, side=Side.BUY, strength=strength,
            reason_codes=["breakout_above_resistance_with_volume"],
            stop_hint=resistance * 0.98,  # stop below the breakout level
            target_hint=current_price + (current_price - resistance) * self.p["target_r"],
        ))
