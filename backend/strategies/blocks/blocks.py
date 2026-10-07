"""Block functions: does a setup fire / does a filter pass on this bar.

Pure over SymbolState. Missing data (warm-up, no previous close, no regime) is
always False, never a guess.
"""
from datetime import time

from backend.strategies.blocks.state import SymbolState


def _hm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def setup_fires(name: str, params: dict, s: SymbolState, side: str) -> bool:
    bar, prev = s.last_bar, s.prev_bar
    if bar is None:
        return False
    long = side == "long"
    two = prev is not None and s.bars_today >= 2  # previous bar is from today

    if name == "orb_break":
        m = params["range_minutes"]
        level = s.range_high(m) if long else s.range_low(m)
        if level is None or not two:
            return False
        return prev.close <= level < bar.close if long else prev.close >= level > bar.close
    if name == "gap":
        if not s.prev_close:
            return False
        pct = (s.open / s.prev_close - 1) * 100
        return pct >= params["min_pct"] if params["direction"] == "up" else pct <= -params["min_pct"]
    if name == "vwap_cross":
        if not two or s.prev_vwap is None or s.vwap is None:
            return False
        if params["mode"] == "reclaim":
            return prev.close < s.prev_vwap and bar.close > s.vwap
        return prev.close > s.prev_vwap and bar.close < s.vwap
    if name == "rsi_cross":
        p, level = params["period"], params["level"]
        before, now = s.prev_rsi(p), s.rsi(p)
        if before is None or now is None:
            return False
        return before < level <= now if params["direction"] == "up" else before > level >= now
    if name == "ema_pullback":
        e = s.ema(params["period"])
        if e is None or not two:
            return False
        if long:
            return prev.low <= e and bar.close > prev.high and bar.close > e
        return prev.high >= e and bar.close < prev.low and bar.close < e
    if name == "volume_spike":
        return s.vol_avg20 is not None and bar.volume >= params["multiple"] * s.vol_avg20
    return False


def filter_passes(name: str, params: dict, s: SymbolState, regime: str | None,
                  sector_rs: float | None, now_ist: time) -> bool:
    if name == "time_window":
        return _hm(params["start"]) <= now_ist < _hm(params["end"])
    if name == "regime_is":
        return regime is not None and regime in params["regimes"]
    if name == "sector_rs":
        return sector_rs is not None and sector_rs >= params["min"]
    if name == "atr_pct":
        if s.atr is None or not s.close:
            return False
        return params["min"] <= s.atr / s.close * 100 <= params["max"]
    if name == "price_vs_vwap":
        if s.vwap is None or s.close is None:
            return False
        return s.close > s.vwap if params["side"] == "above" else s.close < s.vwap
    if name == "volume_confirm":
        bar = s.last_bar
        return bar is not None and s.vol_avg20 is not None and bar.volume >= params["multiple"] * s.vol_avg20
    return False
