"""New intraday strategy (SPEC-intraday-strategies-expansion, CAP-3). Reuses
Indicators.calculate_all's rsi_14/ema_9/atr_14 columns. RSI momentum
thresholds (60/40, not the classic 70/30 reversal bands) paired with
price-vs-ema9 as trend confirmation, since this is a momentum-continuation
scalp, not a reversal play (that's mean_reversion.py's job).
"""

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe

RSI_BULL_THRESHOLD = 60.0
MIN_RSI_JUMP = 5.0  # ponytail: filters slow drifts over the line -- 6 trades/25% win/PF 0.20 as-tuned before this, see spec memlog


class RSIMomentumScalpStrategy(TokenResolvingStrategy):
    PARAMS = {"bull": RSI_BULL_THRESHOLD, "min_jump": MIN_RSI_JUMP}
    GRID = {"bull": [60.0, 65.0], "min_jump": [3.0, 5.0, 8.0]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="rsi_momentum_scalp", mode="INTRADAY", timeframe="5m",
            warmup_bars=20, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return

        history = ctx.history(symbol, self.spec.warmup_bars)
        if len(history) < self.spec.warmup_bars:
            return

        df = Indicators.calculate_all(bars_to_dataframe(history))
        curr_rsi, prev_rsi = df["rsi_14"].iloc[-1], df["rsi_14"].iloc[-2]
        curr_price, curr_ema9 = df["close"].iloc[-1], df["ema_9"].iloc[-1]
        atr = df["atr_14"].iloc[-1]
        if pd.isna(atr):
            return

        rsi_jump = curr_rsi - prev_rsi

        bull, bear, jump = self.p["bull"], 100 - self.p["bull"], self.p["min_jump"]
        if prev_rsi <= bull < curr_rsi and rsi_jump >= jump and curr_price > curr_ema9:
            ctx.submit(Intent(
                symbol=symbol, side=Side.BUY, strength=0.55,
                reason_codes=["rsi_momentum_scalp"],
                stop_hint=curr_price - atr,
                target_hint=curr_price + 2 * atr,
            ))
        elif prev_rsi >= bear > curr_rsi and -rsi_jump >= jump and curr_price < curr_ema9:
            ctx.submit(Intent(
                symbol=symbol, side=Side.SELL, strength=0.55,
                reason_codes=["rsi_momentum_scalp"],
                stop_hint=curr_price + atr,
                target_hint=curr_price - 2 * atr,
            ))
