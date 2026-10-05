"""Ported from backend/components/quant/strategies.py::MeanReversion. Same
logic and thresholds -- structural port, not a redesign.

Note: the original's target formula checked for a `sma_20` column that
`Indicators.calculate_all` never actually populates (it only adds sma_50/
sma_200), so that branch was always dead code and the target always fell
back to `current_price * 1.05`. Ported as the fallback directly rather than
carrying forward a check that can never be true.

Strength is graded 0.5..0.9 (was a flat 0.7): how oversold RSI is (full at
15), how far price is stretched below the lower band (full at 1 ATR), and
whether the 200-day trend is still up -- a dip in an uptrend reverts more
reliably than a fall in a downtrend.
"""

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.strength import graded, ramp, sma
from backend.strategies.card import StrategyCard


class MeanReversionStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="reversion", regimes=["neutral", "risk_off"], needs=["range_day"],
        best_when="A quality stock is oversold against its own range without bad news behind it.",
        avoid_when="A stock falling on real bad news, where cheap gets cheaper.",
        typical_hold_minutes=3750,
    )
    PARAMS = {"rsi_max": 30.0, "target_pct": 0.05}
    GRID = {"rsi_max": [25.0, 30.0, 35.0], "target_pct": [0.05, 0.08]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="mean_reversion", mode="LONGTERM", timeframe="1d",
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
        rsi = df["rsi_14"].iloc[-1]
        lower_band = df["bb_lower"].iloc[-1]

        # Buy condition: RSI oversold AND price below the lower Bollinger band.
        if not (rsi < self.p["rsi_max"] and current_price < lower_band):
            return

        sma_200 = sma([b.close for b in ctx.history(symbol, 200)], 200)
        strength = graded(
            0.5, 0.9,
            ramp(self.p["rsi_max"] - rsi, 0.0, 15.0),
            ramp((lower_band - current_price) / df["atr_14"].iloc[-1], 0.0, 1.0),
            ramp(None if sma_200 is None else current_price - sma_200, 0.0, 0.0),
        )
        ctx.submit(Intent(
            symbol=symbol, side=Side.BUY, strength=strength,
            reason_codes=["oversold_rsi_below_lower_band"],
            stop_hint=current_price * 0.95,
            target_hint=current_price * (1 + self.p["target_pct"]),
        ))
