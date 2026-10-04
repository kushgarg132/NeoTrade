"""New intraday strategy (SPEC-intraday-strategies-expansion, CAP-1). Reuses
Indicators.calculate_all's vwap/atr_14 columns (backend/components/quant/
indicators.py) -- vwap was already implemented there but unused by any
Strategy subclass before this.

Requests a full-session window (SESSION_LOOKBACK_BARS) rather than just
`warmup_bars` bars -- VWAP is a session-cumulative average, so the sliding
20-bar window every other ported strategy uses would silently start the
session mid-day and understate true VWAP. `warmup_bars` still gates when the
strategy is willing to fire (needs at least 2 bars in *today's* session to
compare deviation).
"""

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe

SESSION_LOOKBACK_BARS = 100  # > 75 5m bars/session (09:15-15:30 IST), covers a full NSE day
DEVIATION_THRESHOLD = 0.006  # ponytail: 0.6%, tuned down from an initial 1.5% that barely ever fired (2 trades/59d backtest) -- see spec memlog


class VWAPReversionStrategy(TokenResolvingStrategy):
    PARAMS = {"deviation": DEVIATION_THRESHOLD}
    GRID = {"deviation": [0.004, 0.006, 0.008, 0.012]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="vwap_reversion", mode="INTRADAY", timeframe="5m",
            warmup_bars=2, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return

        history = ctx.history(symbol, SESSION_LOOKBACK_BARS)
        if not history:
            return
        session_date = history[-1].timestamp.date()
        session_bars = [b for b in history if b.timestamp.date() == session_date]
        if len(session_bars) < self.spec.warmup_bars:
            return

        df = Indicators.calculate_all(bars_to_dataframe(session_bars))
        curr_close, curr_vwap = df["close"].iloc[-1], df["vwap"].iloc[-1]
        prev_close, prev_vwap = df["close"].iloc[-2], df["vwap"].iloc[-2]
        atr = df["atr_14"].iloc[-1]
        if pd.isna(atr) or pd.isna(prev_vwap):
            return

        prev_dev = (prev_close - prev_vwap) / prev_vwap
        reverting_up = curr_close > prev_close
        reverting_down = curr_close < prev_close

        if prev_dev <= -self.p["deviation"] and reverting_up:
            ctx.submit(Intent(
                symbol=symbol, side=Side.BUY, strength=0.6,
                reason_codes=["vwap_reversion"],
                stop_hint=curr_close - atr,
                target_hint=curr_vwap,
            ))
        elif prev_dev >= self.p["deviation"] and reverting_down:
            ctx.submit(Intent(
                symbol=symbol, side=Side.SELL, strength=0.6,
                reason_codes=["vwap_reversion"],
                stop_hint=curr_close + atr,
                target_hint=curr_vwap,
            ))
