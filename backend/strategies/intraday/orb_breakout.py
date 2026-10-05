"""New intraday strategy (SPEC-intraday-strategies-expansion, CAP-2).
Opening Range Breakout: the first 15 minutes of the session (09:15-09:30
IST NSE convention -- see SPEC.md Assumptions) set a high/low range; a later
bar clearing that range on above-average volume is the breakout signal.

Requests SESSION_LOOKBACK_BARS like vwap_reversion.py, for the same reason:
the range anchor is the session's first bars, not whatever the last
`warmup_bars` bars happen to be.
"""

from datetime import timedelta
from typing import Optional

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.card import StrategyCard

SESSION_LOOKBACK_BARS = 100
OPENING_RANGE_MINUTES = 15


class ORBStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="breakout", regimes=["risk_on", "neutral"], needs=["volume_spike"],
        best_when="A clean opening range breaks on above-average volume in a trending tape.",
        avoid_when="A choppy open or a high-impact event due within the hour.",
        typical_hold_minutes=90,
    )
    PARAMS = {"range_minutes": OPENING_RANGE_MINUTES, "volume_mult": 1.5}
    GRID = {"range_minutes": [15, 30], "volume_mult": [1.0, 1.5, 2.0]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="orb_breakout", mode="INTRADAY", timeframe="5m",
            warmup_bars=4, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is not None and (intent := self.signal(ctx, symbol)) is not None:
            ctx.submit(intent)

    def signal(self, ctx, symbol: str) -> Optional[Intent]:
        history = ctx.history(symbol, SESSION_LOOKBACK_BARS)
        if not history:
            return None
        session_date = history[-1].timestamp.date()
        session_bars = [b for b in history if b.timestamp.date() == session_date]
        if len(session_bars) < self.spec.warmup_bars:
            return None

        range_end = session_bars[0].timestamp + timedelta(minutes=self.p["range_minutes"])
        range_bars = [b for b in session_bars if b.timestamp < range_end]
        breakout_bars = [b for b in session_bars if b.timestamp >= range_end]
        if not range_bars or not breakout_bars:
            return None  # still inside (or hasn't reached) the opening range

        or_high = max(b.high for b in range_bars)
        or_low = min(b.low for b in range_bars)
        avg_range_volume = sum(b.volume for b in range_bars) / len(range_bars)

        current = breakout_bars[-1]
        # tuned from > avg_range_volume (218 trades/59d backtest, PF 0.93 --
        # net loser, too many marginal whipsaw breakouts) -- see spec memlog
        if current.volume <= self.p["volume_mult"] * avg_range_volume:
            return None

        df = Indicators.calculate_all(bars_to_dataframe(session_bars))
        atr = df["atr_14"].iloc[-1]
        if pd.isna(atr):
            return None

        # Require the close to clear the range by a real margin (0.3 ATR),
        # not just tick past it -- filters marginal breakouts that whipsaw
        # straight back. Stop is ATR-based, not the full opposite range edge
        # (that was too wide a risk relative to the 2*ATR target).
        if current.close > or_high + 0.3 * atr:
            return Intent(
                symbol=symbol, side=Side.BUY, strength=0.65,
                reason_codes=["orb_breakout"],
                stop_hint=current.close - 1.5 * atr,
                target_hint=current.close + 2 * atr,
            )
        elif current.close < or_low - 0.3 * atr:
            return Intent(
                symbol=symbol, side=Side.SELL, strength=0.65,
                reason_codes=["orb_breakout"],
                stop_hint=current.close + 1.5 * atr,
                target_hint=current.close - 2 * atr,
            )
        return None
