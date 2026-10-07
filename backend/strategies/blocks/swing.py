"""Swing block functions: does a setup fire / does a filter pass on this daily bar.

Pure over SwingState. Missing data (warm-up, no rank, no regime) is always False.
Cross-sectional inputs (rank_pct, sector_rs) are computed by the caller.
"""
from backend.strategies.blocks.swing_state import SwingState

_CRORE = 1e7


def setup_fires(name: str, params: dict, s: SwingState, rank_pct: float | None) -> bool:
    if s.close is None:
        return False
    if name == "breakout_n":
        hi = s.high_n(int(params["days"]))
        return hi is not None and s.close > hi
    if name == "pullback_ma":
        trend, pull = s.sma(int(params["trend"])), s.sma(int(params["pull"]))
        if trend is None or pull is None or s.prev_low is None:
            return False
        return s.close > trend and s.prev_low <= pull and s.close > s.prev_high
    if name == "rsi2_dip":
        ma = s.sma(200)
        return s.rsi2 is not None and ma is not None and s.rsi2 < params["level"] and s.close > ma
    if name == "gap_hold":
        if not s.prev_close:
            return False
        return s.open >= s.prev_close * (1 + params["min_pct"] / 100) and s.close >= s.open
    if name == "momentum_rank":  # rank_pct is for params["lookback"], supplied by the caller
        return rank_pct is not None and rank_pct <= params["top_pct"]
    if name == "volume_breakout":
        if s.vol_avg20 is None or s.high <= s.low:
            return False
        return s.volume >= params["multiple"] * s.vol_avg20 and s.close >= s.low + 0.75 * (s.high - s.low)
    return False


def filter_passes(name: str, params: dict, s: SwingState, regime: str | None,
                  sector_rs: float | None) -> bool:
    if s.close is None:
        return False
    if name == "trend_ma":
        ma = s.sma(int(params["period"]))
        return ma is not None and s.close > ma
    if name == "regime_is":
        return regime is not None and regime in params["regimes"]
    if name == "sector_rs":
        return sector_rs is not None and sector_rs >= params["min"]
    if name == "atr_pct":
        return s.atr is not None and params["min"] <= s.atr / s.close * 100 <= params["max"]
    if name == "liquidity":
        return s.turnover_avg20 is not None and s.turnover_avg20 >= params["min_cr"] * _CRORE
    return False
