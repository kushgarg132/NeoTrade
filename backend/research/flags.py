"""Plain-fact chips for a stock snapshot (backend.research.quick).

Each flag states a fact the trader would otherwise work out from the
figures -- "Above 200-day avg", "Net cash" -- never a buy or sell call
(PRODUCT.md: nothing sold here is advice). No LLM; a flag whose inputs
are missing is simply left out.
"""

from typing import Optional

_TREND = {"up": ("Uptrend", "up"), "down": ("Downtrend", "down"), "choppy": ("Sideways", "neutral")}


def _flag(code: str, label: str, tone: str) -> dict:
    return {"code": code, "label": label, "tone": tone}


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def stock_flags(technicals: dict, company: dict) -> list[dict]:
    t, c = technicals or {}, company or {}
    price, sma_50, sma_200 = _num(t.get("price")), _num(t.get("sma_50")), _num(t.get("sma_200"))
    rsi, volume_ratio = _num(t.get("rsi")), _num(t.get("volume_ratio"))
    high = _num(c.get("week_52_high")) or _num(t.get("high_52w"))
    low = _num(c.get("week_52_low")) or _num(t.get("low_52w"))
    debt, cash = _num(c.get("total_debt")), _num(c.get("total_cash"))
    eps, dividend = _num(c.get("trailing_eps")), _num(c.get("dividend_yield"))
    flags = []

    if t.get("trend") in _TREND:
        flags.append(_flag("trend", *_TREND[t["trend"]]))
    if price is not None and sma_200:
        flags.append(_flag("vs_200", *(("Above 200-day avg", "up") if price >= sma_200 else ("Below 200-day avg", "down"))))
    if sma_50 is not None and sma_200:
        flags.append(_flag("cross", *(("Golden cross", "up") if sma_50 >= sma_200 else ("Death cross", "down"))))
    if rsi is not None and rsi > 70:
        flags.append(_flag("rsi", f"RSI {round(rsi)} · overbought", "down"))
    elif rsi is not None and rsi < 30:
        flags.append(_flag("rsi", f"RSI {round(rsi)} · oversold", "up"))
    if price is not None and high and price >= 0.95 * high:
        flags.append(_flag("near_high", "Near 52-week high", "neutral"))
    if price is not None and low and price <= 1.05 * low:
        flags.append(_flag("near_low", "Near 52-week low", "neutral"))
    if volume_ratio is not None and volume_ratio >= 1.5:
        flags.append(_flag("volume", f"Volume {volume_ratio:.1f}× avg", "neutral"))
    if debt is not None and cash is not None:
        flags.append(_flag("cash", *(("Debt > cash", "down") if debt > cash else ("Net cash", "up"))))
    if eps is not None and eps < 0:
        flags.append(_flag("loss", "Loss-making", "down"))
    if dividend:
        flags.append(_flag("dividend", f"Dividend {dividend * 100:.1f}%", "neutral"))
    return flags
