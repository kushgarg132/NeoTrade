"""Gap-and-go: a stock gaps on overnight news (a catalyst from
backend/datalayer/catalysts.py, handed in at construction) and, once its
opening range is set, breaks out of it in the news' direction on volume
without having given back the far side of the range first."""

from typing import Optional

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy
from backend.strategies.card import StrategyCard
from backend.strategies.intraday.gaps import (
    SESSION_LOOKBACK_BARS, gap_pct, opening_range, previous_close, split_sessions,
)


class GapAndGoStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="momentum", regimes=["risk_on", "neutral"], needs=["gap", "catalyst", "volume_spike"],
        best_when="A stock gaps on material overnight news and keeps going in the news' direction.",
        avoid_when="A gap with no news behind it, or news the market already knew.",
        typical_hold_minutes=120,
    )
    PARAMS = {"gap_pct": 2.0, "volume_mult": 1.5, "range_minutes": 15}
    GRID = {"gap_pct": [1.5, 2.0, 3.0], "volume_mult": [1.0, 1.5, 2.0]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None,
                 catalysts: dict[str, dict[str, float]] | None = None,
                 prev_closes: dict[str, dict[str, float]] | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.catalysts = catalysts or {}
        self.prev_closes = prev_closes or {}
        self.spec = StrategySpec(name="gap_and_go", mode="INTRADAY", timeframe="5m", warmup_bars=4, universe=universe)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is not None and (intent := self.signal(ctx, symbol)) is not None:
            ctx.submit(intent)

    def signal(self, ctx, symbol: str) -> Optional[Intent]:
        today, prior = split_sessions(ctx.history(symbol, SESSION_LOOKBACK_BARS))
        prev_close = previous_close(today, prior, self.prev_closes, symbol)
        gap = gap_pct(today, prev_close)
        if gap is None or len(today) < self.spec.warmup_bars:
            return None
        catalyst = self.catalysts.get(today[0].timestamp.date().isoformat(), {}).get(symbol)
        range_bars, after = opening_range(today, self.p["range_minutes"])
        if not catalyst or not range_bars or not after:
            return None
        high, low = max(b.high for b in range_bars), min(b.low for b in range_bars)
        current = after[-1]
        if current.volume < self.p["volume_mult"] * sum(b.volume for b in range_bars) / len(range_bars):
            return None
        codes = ["gap_and_go", "news_catalyst"]
        if catalyst > 0 and gap >= self.p["gap_pct"] and current.close > high and min(b.low for b in after) >= low:
            return Intent(symbol=symbol, side=Side.BUY, strength=0.7, reason_codes=codes,
                          stop_hint=low, target_hint=current.close + 2 * (current.close - low))
        if catalyst < 0 and gap <= -self.p["gap_pct"] and current.close < low and max(b.high for b in after) <= high:
            return Intent(symbol=symbol, side=Side.SELL, strength=0.7, reason_codes=codes,
                          stop_hint=high, target_hint=current.close - 2 * (high - current.close))
        return None
