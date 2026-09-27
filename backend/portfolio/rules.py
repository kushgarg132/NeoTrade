"""SELL / HOLD / ADD for each holding, by rules first.

Each holding is checked against plain rules (below its 200-day average,
further under its cost than the user's limit, three quarters of falling
profit, ...). The rules that fire become an Intent, with their names as
reason codes and their summed weight as its strength, scored by the one
conviction formula (backend/scoring/composite.py). So the AI -- here the
stock's news sentiment -- moves conviction by at most AI_CAP, and a verdict
the rules did not support below RULE_FLOOR cannot exist: that holding is a
HOLD. The AI write-up (backend/portfolio/review.py) explains verdicts; it
never makes one. Pure, no I/O.
"""

from typing import Optional

from backend.core.models import Intent, Side
from backend.portfolio.health import profit_trend
from backend.scoring.composite import score_intent

# Weight of each rule toward a SELL / ADD strength. RULE_FLOOR is 0.45, so
# one rule alone never makes a verdict; two strong ones do.
SELL_RULES = {
    "loss_beyond_limit": 0.30,
    "earnings_falling_3q": 0.30,
    "below_200dma": 0.25,
    "overweight": 0.20,
    "high_debt": 0.15,
}
ADD_RULES = {
    "earnings_rising_3q": 0.30,
    "uptrend": 0.25,
    "strong_roe": 0.15,
    "reasonable_valuation": 0.10,
}
HIGH_DEBT = 2.0      # debt/equity, times
STRONG_ROE = 0.15    # 15%
MAX_PE = 40.0


def sell_codes(row: dict, health: dict, limits: dict) -> list[str]:
    trend, fundamentals = health.get("trend") or {}, health.get("fundamentals") or {}
    codes = []
    if row.get("pnl_pct") is not None and row["pnl_pct"] <= -limits["max_loss_pct"]:
        codes.append("loss_beyond_limit")
    if profit_trend(fundamentals.get("quarterly_profit") or []) == "falling":
        codes.append("earnings_falling_3q")
    if trend.get("sma_200") and trend["close"] < trend["sma_200"]:
        codes.append("below_200dma")
    if row.get("weight_pct") is not None and row["weight_pct"] > limits["max_weight_pct"]:
        codes.append("overweight")
    if (fundamentals.get("debt_to_equity") or 0) > HIGH_DEBT:
        codes.append("high_debt")
    return codes


def add_codes(row: dict, health: dict, limits: dict) -> list[str]:
    trend, fundamentals = health.get("trend") or {}, health.get("fundamentals") or {}
    # Never suggest adding to a holding already at the user's size limit.
    if row.get("weight_pct") is not None and row["weight_pct"] >= limits["max_weight_pct"]:
        return []
    codes = []
    if profit_trend(fundamentals.get("quarterly_profit") or []) == "rising":
        codes.append("earnings_rising_3q")
    if trend.get("sma_50") and trend.get("sma_200") and trend["close"] > trend["sma_50"] > trend["sma_200"]:
        codes.append("uptrend")
    if (fundamentals.get("roe") or 0) >= STRONG_ROE:
        codes.append("strong_roe")
    if fundamentals.get("pe") and 0 < fundamentals["pe"] <= MAX_PE:
        codes.append("reasonable_valuation")
    return codes


def _scored(symbol: str, side: Side, codes: list[str], weights: dict, sentiment: Optional[float]):
    if not codes:
        return None
    intent = Intent(
        symbol=symbol, side=side, strength=min(sum(weights[c] for c in codes), 1.0), reason_codes=codes,
    )
    # Sentiment is oriented to the verdict: good news argues against selling.
    ai = None if sentiment is None else (-sentiment if side == Side.SELL else sentiment)
    return score_intent(intent, ai)


def stock_verdict(row: dict, health: dict, limits: dict, sentiment: Optional[float]) -> dict:
    sells = sell_codes(row, health, limits)
    adds = add_codes(row, health, limits)
    sell = _scored(row["symbol"], Side.SELL, sells, SELL_RULES, sentiment)
    add = _scored(row["symbol"], Side.BUY, adds, ADD_RULES, sentiment)
    if sell is not None and (add is None or sell.final >= add.final):
        verdict, score, codes = "SELL", sell, sells
    elif add is not None:
        verdict, score, codes = "ADD", add, adds
    else:
        # Below the floor both ways: say which rules did fire, as facts.
        verdict, score, codes = "HOLD", None, sells + adds
    return {
        "verdict": verdict, "reason_codes": codes,
        "score": None if score is None else {
            "final": round(score.final, 3), "rule": score.rule_score, "ai": score.ai_score,
        },
    }


def fund_verdict(row: dict, limits: dict) -> dict:
    """Funds and ETFs get REVIEW or KEEP, not sell calls: the app has no
    data on what they hold or cost yet."""
    codes = []
    if row.get("pnl_pct") is not None and row["pnl_pct"] <= -limits["max_loss_pct"]:
        codes.append("loss_beyond_limit")
    if row.get("weight_pct") is not None and row["weight_pct"] > limits["max_weight_pct"] * 2:
        codes.append("overweight")
    return {"verdict": "REVIEW" if codes else "KEEP", "reason_codes": codes, "score": None}


# How much worse a verdict is than another, for "what got worse this week".
SEVERITY = {"ADD": 0, "KEEP": 0, "HOLD": 1, "REVIEW": 2, "SELL": 2}


def worsened(previous: Optional[str], current: str) -> bool:
    return previous is not None and SEVERITY.get(current, 0) > SEVERITY.get(previous, 0) and current in ("SELL", "REVIEW")
