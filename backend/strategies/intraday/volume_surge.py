"""Ported from backend/components/quant/strategies.py::VolumeSurge. Same
logic and thresholds -- structural port, not a redesign.

`warmup_bars=20` matches the original's 20-period rolling volume average
window, kept as-is per the brief. Flag: at this strategy's 5m timeframe that
window is ~100 minutes of bars, not the 20 *days* the original implicitly
saw when fed daily candles from QuantAgent -- a shorter volume baseline than
the original's daily-bar context, timeframe-appropriate but not identical
in what it's really averaging. Not changed here; a real 5m-tuned window is
Task 7's call (this task is a mechanical port only).

No indicator prerequisites here -- the original didn't call
`Indicators.calculate_all` for this one either, it only needs raw
open/close/volume.
"""

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe
from backend.strategies.card import StrategyCard


class VolumeSurgeStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="momentum", regimes=["risk_on", "neutral"], needs=["volume_spike"],
        best_when="A bar prints several times normal volume with a decisive close.",
        avoid_when="Low-liquidity names or news-free spikes late in the session.",
        typical_hold_minutes=60,
    )
    PARAMS = {"volume_mult": 3.0}
    GRID = {"volume_mult": [2.0, 3.0, 4.0, 5.0]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.spec = StrategySpec(
            name="volume_surge", mode="INTRADAY", timeframe="5m",
            warmup_bars=20, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return

        history = ctx.history(symbol, self.spec.warmup_bars)
        if len(history) < self.spec.warmup_bars:
            return

        df = bars_to_dataframe(history)
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        current_vol = df["volume"].iloc[-1]
        current_price = df["close"].iloc[-1]

        if current_vol <= self.p["volume_mult"] * avg_vol:
            return

        if df["close"].iloc[-1] > df["open"].iloc[-1]:
            ctx.submit(Intent(
                symbol=symbol, side=Side.BUY, strength=0.6,
                reason_codes=["massive_buying_volume"],
                stop_hint=current_price * 0.98,
                target_hint=current_price * 1.05,
            ))
        else:
            ctx.submit(Intent(
                symbol=symbol, side=Side.SELL, strength=0.6,
                reason_codes=["massive_selling_volume"],
                stop_hint=current_price * 1.02,
                target_hint=current_price * 0.95,
            ))
