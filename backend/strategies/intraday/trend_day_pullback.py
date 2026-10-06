"""Trend-day pullback: on a day trending one way (price on the right side
of VWAP, the slow EMA sloping with it), the first dip into the fast/slow
EMAs that holds the slow EMA, followed by a bar clearing the dip, rejoins
the trend. Today's bars only."""

from typing import Optional

import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.card import StrategyCard
from backend.strategies.intraday.gaps import SESSION_LOOKBACK_BARS, split_sessions


class TrendDayPullbackStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="momentum", regimes=["risk_on", "neutral"], needs=["trend_day"],
        best_when="A one-way day where price rides above VWAP and dips only briefly to its EMAs.",
        avoid_when="Range-bound or choppy days where price keeps crossing VWAP.",
        typical_hold_minutes=60,
    )
    PARAMS = {"ema_fast": 9, "ema_slow": 20, "slope_bars": 6}
    GRID = {"slope_bars": [4, 6, 8]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(name="trend_day_pullback", mode="INTRADAY", timeframe="5m", warmup_bars=12,
                                 universe=universe)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is not None and (intent := self.signal(ctx, symbol)) is not None:
            ctx.submit(intent)

    def signal(self, ctx, symbol: str) -> Optional[Intent]:
        today, _ = split_sessions(ctx.history(symbol, SESSION_LOOKBACK_BARS))
        slope = self.p["slope_bars"]
        if len(today) < max(self.spec.warmup_bars, slope + 2):
            return None
        # Only the two columns used: calculate_all on every bar of every symbol
        # made a year's backtest run for hours.
        df = bars_to_dataframe(today)
        fast = Indicators.ema(df["close"], self.p["ema_fast"])
        slow = Indicators.ema(df["close"], self.p["ema_slow"])
        atr = Indicators.atr(df["high"], df["low"], df["close"]).iloc[-1]
        session = pd.to_datetime(df["timestamp"]).dt.normalize() if "timestamp" in df.columns else None
        vwap = Indicators.vwap(df["high"], df["low"], df["close"], df["volume"], session).iloc[-1]
        if pd.isna(atr) or pd.isna(vwap):
            return None
        prev, cur = today[-2], today[-1]
        close = cur.close
        if close > vwap and slow.iloc[-1] > slow.iloc[-1 - slope] \
                and prev.low <= max(fast.iloc[-2], slow.iloc[-2]) and prev.close >= slow.iloc[-2] \
                and close > prev.high:
            stop = min(prev.low, slow.iloc[-2]) - 0.5 * atr
            return Intent(symbol=symbol, side=Side.BUY, strength=0.65, reason_codes=["trend_day_pullback"],
                          stop_hint=stop, target_hint=close + 2 * (close - stop))
        if close < vwap and slow.iloc[-1] < slow.iloc[-1 - slope] \
                and prev.high >= min(fast.iloc[-2], slow.iloc[-2]) and prev.close <= slow.iloc[-2] \
                and close < prev.low:
            stop = max(prev.high, slow.iloc[-2]) + 0.5 * atr
            return Intent(symbol=symbol, side=Side.SELL, strength=0.65, reason_codes=["trend_day_pullback"],
                          stop_hint=stop, target_hint=close - 2 * (stop - close))
        return None
