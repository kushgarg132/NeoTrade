"""Ported from backend/components/quant/strategies.py::MACDCrossover. Same
logic and thresholds -- structural port, not a redesign.

Strength is graded 0.5..0.9 (was a flat 0.75): whether the crossover agrees
with the 200-day trend, how much momentum the histogram already has (full
at 0.25 ATR), and how much room RSI has before overbought/oversold."""

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.strength import graded, ramp, sma
from backend.strategies.card import StrategyCard


class MACDCrossoverStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="momentum", regimes=["risk_on", "neutral"], needs=["trend_day"],
        best_when="A fresh MACD crossover starts a new daily trend.",
        avoid_when="Flat, range-bound tape, where crossovers whipsaw.",
        typical_hold_minutes=7500,
    )
    PARAMS = {"stop_pct": 0.03, "target_pct": 0.06}
    GRID = {"stop_pct": [0.02, 0.03, 0.05], "target_pct": [0.06, 0.10]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="macd_crossover", mode="LONGTERM", timeframe="1d",
            warmup_bars=30, universe=universe,
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
        curr_hist = df["macd_hist"].iloc[-1]
        prev_hist = df["macd_hist"].iloc[-2]

        sma_200 = sma([b.close for b in ctx.history(symbol, 200)], 200)
        trend = None if sma_200 is None else current_price - sma_200
        atr = df["atr_14"].iloc[-1]
        rsi = df["rsi_14"].iloc[-1]

        if prev_hist < 0 and curr_hist > 0:
            strength = graded(
                0.5, 0.9,
                ramp(trend, 0.0, 0.0),
                ramp(curr_hist / atr, 0.0, 0.25),
                ramp(70 - rsi, 0.0, 20.0),
            )
            ctx.submit(Intent(
                symbol=symbol, side=Side.BUY, strength=strength,
                reason_codes=["macd_bullish_crossover"],
                stop_hint=current_price * (1 - self.p["stop_pct"]),
                target_hint=current_price * (1 + self.p["target_pct"]),
            ))
        elif prev_hist > 0 and curr_hist < 0:
            strength = graded(
                0.5, 0.9,
                ramp(None if trend is None else -trend, 0.0, 0.0),
                ramp(-curr_hist / atr, 0.0, 0.25),
                ramp(rsi - 30, 0.0, 20.0),
            )
            ctx.submit(Intent(
                symbol=symbol, side=Side.SELL, strength=strength,
                reason_codes=["macd_bearish_crossover"],
                stop_hint=current_price * (1 + self.p["stop_pct"]),
                target_hint=current_price * (1 - self.p["target_pct"]),
            ))
