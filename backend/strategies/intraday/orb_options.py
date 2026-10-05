"""The opening range breakout, expressed with options: on a breakout it buys
an at-the-money call, on a breakdown an at-the-money put, on the curated
liquid F&O large-caps only (backend/options/resolver.py).

Same trigger as orb_breakout.py, so the two can be compared on paper. The
stop and target stay levels on the underlying; the runner closes the option
when the underlying reaches either, or at the 15:15 square-off. Buying an
option caps the loss at the premium paid, which is what
backend/options/sizing.py sizes against.
"""

from dataclasses import replace

from backend.core.models import Side
from backend.engine.protocols import StrategySpec
from backend.options.resolver import is_fo_eligible
from backend.strategies.intraday.orb_breakout import ORBStrategy
from backend.strategies.card import StrategyCard


class ORBOptionsStrategy(ORBStrategy):
    CARD = StrategyCard(
        style="options", regimes=["risk_on", "neutral"], needs=["volume_spike"],
        best_when="An F&O large-cap breaks its opening range decisively and premiums are live.",
        avoid_when="Premiums are wide or expiry-day decay dominates the move.",
        typical_hold_minutes=60,
    )
    def __init__(self, universe: list[str], symbol_for_token: dict[int, str]) -> None:
        super().__init__(universe, symbol_for_token)
        self.spec = StrategySpec(
            name="orb_options", mode="INTRADAY", timeframe="5m",
            warmup_bars=4, universe=universe,
        )

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None or not is_fo_eligible(symbol):
            return
        intent = self.signal(ctx, symbol)
        if intent is None:
            return
        bullish = intent.side == Side.BUY
        ctx.submit(replace(
            intent, side=Side.BUY,
            reason_codes=[*intent.reason_codes, "buy_call" if bullish else "buy_put"],
            option_flavor="LONG_CALL" if bullish else "LONG_PUT",
        ))
