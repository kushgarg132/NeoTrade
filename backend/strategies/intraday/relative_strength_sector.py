"""Sector relative strength: when a sector moves as a group (the mean
return since the open of the stock's sector peers in this run), the stock
leading that move is bought on its first resumption after a pullback, and
the one lagging a falling sector is sold. Peers come from the same run, so
no index feed is needed; `sector_of` (symbol -> sector, the Nifty 200 file)
is handed in at construction."""

from typing import Optional

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.strategies.base import TokenResolvingStrategy
from backend.strategies.card import StrategyCard
from backend.strategies.intraday.gaps import SESSION_LOOKBACK_BARS, split_sessions


class RelativeStrengthSectorStrategy(TokenResolvingStrategy):
    CARD = StrategyCard(
        style="momentum", regimes=["risk_on", "neutral", "risk_off"], needs=["sector_move"],
        best_when="A sector moves as a group on news and one stock clearly leads or lags it.",
        avoid_when="Quiet sectors, or a stock moving on its own news against its sector.",
        typical_hold_minutes=75,
    )
    PARAMS = {"sector_move_pct": 0.5, "lead_pct": 1.0, "min_peers": 3}
    GRID = {"lead_pct": [0.75, 1.0, 1.5]}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str], params: dict | None = None,
                 sector_of: dict[str, str] | None = None) -> None:
        super().__init__(universe, symbol_for_token, params)
        self.sector_of = sector_of or {}
        # Every symbol's return since the open, computed once per bar time
        # rather than once per symbol: a backtest calls signal() for every
        # symbol on every bar.
        self._returns: tuple[object, dict[str, float]] = (None, {})
        self.spec = StrategySpec(name="relative_strength_sector", mode="INTRADAY", timeframe="5m",
                                 warmup_bars=6, universe=universe)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is not None and (intent := self.signal(ctx, symbol)) is not None:
            ctx.submit(intent)

    def _session_returns(self, ctx, at) -> dict[str, float]:
        if self._returns[0] != at:
            returns = {}
            for s in self._universe:
                if s in self.sector_of:
                    today, _ = split_sessions(ctx.history(s, SESSION_LOOKBACK_BARS))
                    if len(today) >= self.spec.warmup_bars and today[0].timestamp.date() == at.date():
                        returns[s] = self._ret(today)
            self._returns = (at, returns)
        return self._returns[1]

    @staticmethod
    def _ret(bars: list) -> float:
        return (bars[-1].close / bars[0].open - 1) * 100

    def signal(self, ctx, symbol: str) -> Optional[Intent]:
        sector = self.sector_of.get(symbol)
        own, _ = split_sessions(ctx.history(symbol, SESSION_LOOKBACK_BARS))
        if sector is None or len(own) < max(self.spec.warmup_bars, 3):
            return None
        returns = self._session_returns(ctx, own[-1].timestamp)
        peers = [r for s, r in returns.items() if s != symbol and self.sector_of[s] == sector]
        if len(peers) < self.p["min_peers"]:
            return None
        group = sum(peers) / len(peers)
        lead = self._ret(own) - group
        before, prev, cur = own[-3], own[-2], own[-1]
        if group >= self.p["sector_move_pct"] and lead >= self.p["lead_pct"] \
                and prev.close < before.close and cur.close > prev.high:
            return Intent(symbol=symbol, side=Side.BUY, strength=0.65, reason_codes=["relative_strength_sector"],
                          stop_hint=prev.low, target_hint=cur.close + 2 * (cur.close - prev.low))
        if group <= -self.p["sector_move_pct"] and lead <= -self.p["lead_pct"] \
                and prev.close > before.close and cur.close < prev.low:
            return Intent(symbol=symbol, side=Side.SELL, strength=0.65, reason_codes=["relative_strength_sector"],
                          stop_hint=prev.high, target_hint=cur.close - 2 * (prev.high - cur.close))
        return None
