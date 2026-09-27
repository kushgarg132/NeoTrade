"""A cash-secured put (CSP) writer: reuses MeanReversionStrategy's oversold
trigger ("price below the lower Bollinger band, RSI < 30") since "I'd be
happy to own this stock cheaper" is exactly what a CSP expresses -- but
instead of buying the underlying, it emits an option_flavor="CSP" Intent
that backend/engine/runner.py::size_intents dispatches to
backend/options/sizing.py instead of the equity stop-distance sizer.

Only fires for a symbol in backend/options/resolver.py's curated F&O-
eligible list -- most of the mid/small-cap scan universe has no listed
F&O contract at all.
"""

from backend.components.quant.indicators import Indicators
from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.options.resolver import is_fo_eligible
from backend.strategies.base import TokenResolvingStrategy, bars_to_dataframe


class CashSecuredPutStrategy(TokenResolvingStrategy):
    def __init__(self, universe: list[str], symbol_for_token: dict[int, str]) -> None:
        super().__init__(universe, symbol_for_token)
        self.spec = StrategySpec(
            name="cash_secured_put", mode="LONGTERM", timeframe="1d",
            warmup_bars=50, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None or not is_fo_eligible(symbol):
            return

        history = ctx.history(symbol, self.spec.warmup_bars)
        if len(history) < self.spec.warmup_bars:
            return

        df = Indicators.calculate_all(bars_to_dataframe(history))
        current_price = df["close"].iloc[-1]
        rsi = df["rsi_14"].iloc[-1]
        lower_band = df["bb_lower"].iloc[-1]

        if not (rsi < 30 and current_price < lower_band):
            return

        ctx.submit(Intent(
            symbol=symbol, side=Side.SELL, strength=0.7,
            reason_codes=["oversold_rsi_below_lower_band"],
            # Display-only for the suggestion card, not consumed by the
            # option sizer's own strike/expiry math: the underlying levels
            # at which you'd reconsider the position early.
            stop_hint=current_price * 0.90,
            target_hint=current_price * 1.0,
            option_flavor="CSP",
        ))
