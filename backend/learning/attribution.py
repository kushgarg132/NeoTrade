"""Closed paper trades judged by setup. Pure, no I/O.

Each strategy's trades, net of charges, are grouped by reason code, by
market regime at entry (Nifty above or below its 200-day average) and by
signal strength. A group needs MIN_TRADES before it is reported -- ten
trades say little, three say nothing -- and every expectancy is also given
shrunk toward zero, so a small lucky group does not look like an edge.
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import date
from typing import Optional

from backend.analytics import _summary

MIN_TRADES = 10
# Pseudo-trades at zero P&L added to every group's mean: with n real trades
# the shrunk expectancy is sum / (n + PRIOR_TRADES).
PRIOR_TRADES = 10
REGIME_DAYS = 200
STRENGTH_BUCKETS = [(0.6, "<0.6"), (0.8, "0.6–0.8"), (float("inf"), "≥0.8")]


def net(trade: dict) -> float:
    return (trade.get("realized_pnl") or 0.0) - (trade.get("costs") or 0.0)


def shrunk(nets: list[float]) -> float:
    return sum(nets) / (len(nets) + PRIOR_TRADES)


def regime_on(day: date, nifty: list) -> Optional[str]:
    """"up" when the Nifty's last close on or before `day` is above its
    REGIME_DAYS average, "down" below it. `nifty` is [(date, close)] oldest
    first; None without enough history."""
    i = bisect_right([d for d, _ in nifty], day)
    if i < REGIME_DAYS:
        return None
    closes = [c for _, c in nifty[i - REGIME_DAYS:i]]
    return "up" if closes[-1] >= sum(closes) / REGIME_DAYS else "down"


def strength_bucket(strength: float) -> str:
    return next(label for edge, label in STRENGTH_BUCKETS if strength < edge)


def _row(strategy: str, by: str, group: Optional[str], nets: list[float]) -> dict:
    s = _summary(nets)
    return {"strategy": strategy, "by": by, "group": group, **s,
            "expectancy": s["net"] / len(nets), "shrunk": shrunk(nets)}


def attribute(trades: list[dict], nifty: list) -> list[dict]:
    """`trades` are closed trades with a `strategy`; `context` (from
    Order.context) may be None, which leaves them out of the reason and
    strength groups only. One "all" row per strategy, always."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    for t in sorted(trades, key=lambda t: t["exit_at"]):
        name, n = t["strategy"], net(t)
        groups[(name, "all", None)].append(n)
        regime = regime_on(t["entry_at"].date(), nifty)
        if regime:
            groups[(name, "regime", regime)].append(n)
        ctx = t.get("context") or {}
        for code in ctx.get("reason_codes") or []:
            groups[(name, "reason", code)].append(n)
        if ctx.get("strength") is not None:
            groups[(name, "strength", strength_bucket(ctx["strength"]))].append(n)
    return [_row(*key, nets) for key, nets in groups.items()
            if key[1] == "all" or len(nets) >= MIN_TRADES]
