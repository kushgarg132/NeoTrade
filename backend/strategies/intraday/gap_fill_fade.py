"""Gap-fill fade: a gap with no overnight news behind it (no catalyst in
the gap's direction from backend/datalayer/catalysts.py) that cannot hold
its opening range is faded back toward the previous close. News is what
tells this apart from gap_and_go.py."""

from typing import Optional

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy
from backend.strategies.card import StrategyCard
from backend.strategies.intraday.gaps import (
    SESSION_LOOKBACK_BARS, gap_pct, opening_range, previous_close, split_sessions,
)


class GapFillFadeStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="reversion", regimes=["neutral", "risk_off"], needs=["gap"],
        best_when="A stock gaps without news to support it and fails to hold its opening range.",
        avoid_when="Gaps driven by real news, or strong trend days.",
        typical_hold_minutes=90,
    )
    PARAMS = {"gap_pct": 1.5, "range_minutes": 15}
    GRID = {"gap_pct": [1.0, 1.5, 2.5]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None,
                 catalysts: dict[str, dict[str, float]] | None = None,
                 prev_closes: dict[str, dict[str, float]] | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.catalysts = catalysts or {}
        self.prev_closes = prev_closes or {}
        self.spec = StrategySpec(name="gap_fill_fade", mode="INTRADAY", timeframe="5m", warmup_bars=4,
                                 universe=universe)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is not None and (intent := self.signal(ctx, symbol)) is not None:
            ctx.submit(intent)

    def signal(self, ctx, symbol: str) -> Optional[Intent]:
        today, prior = split_sessions(ctx.history(symbol, SESSION_LOOKBACK_BARS))
        prev_close = previous_close(today, prior, self.prev_closes, symbol)
        gap = gap_pct(today, prev_close)
        if gap is None or len(today) < self.spec.warmup_bars or abs(gap) < self.p["gap_pct"]:
            return None
        catalyst = self.catalysts.get(today[0].timestamp.date().isoformat(), {}).get(symbol) or 0.0
        if catalyst * gap > 0:  # the news backs the gap: not a fade
            return None
        range_bars, after = opening_range(today, self.p["range_minutes"])
        if not range_bars or not after:
            return None
        high, low = max(b.high for b in range_bars), min(b.low for b in range_bars)
        close, target = after[-1].close, prev_close
        if gap > 0 and close < low and target < close:
            return Intent(symbol=symbol, side=Side.SELL, strength=0.6, reason_codes=["gap_fill_fade"],
                          stop_hint=high, target_hint=target)
        if gap < 0 and close > high and target > close:
            return Intent(symbol=symbol, side=Side.BUY, strength=0.6, reason_codes=["gap_fill_fade"],
                          stop_hint=low, target_hint=target)
        return None
