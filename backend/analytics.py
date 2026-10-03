"""P&L aggregates for the dashboard cards.

Boundaries are IST, the market's own day: a trade closed at 23:00 IST is
today's trade, and truncating in UTC would file it under yesterday. Trades
come out of `paper_trades` (round trips), not fills, so "3 trades today"
means three round trips rather than however many executions they took.
"""

from datetime import datetime, timezone
from typing import Optional

from backend.core.models import Venue
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST


def _ist(value: datetime) -> datetime:
    """Mongo hands datetimes back naive-as-UTC; give them a zone before
    comparing against an IST boundary."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST)


async def compute_pnl(
    ledger: LedgerStore, mark_prices: dict[str, float], now: Optional[datetime] = None,
    venue: Optional[Venue] = None, mode: Optional[str] = None,
) -> dict:
    """`venue` narrows every figure to one book (paper or live); None keeps
    the combined view. `mode` (INTRADAY / LONGTERM) narrows to one engine's
    trades; positions are per symbol, not per mode, so with a mode the open
    figures come from that mode's OPEN trades instead."""
    now = _ist(now or datetime.now(timezone.utc))
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    closed = [
        t for t in await ledger.get_trades(status="CLOSED", limit=2000, venue=venue, mode=mode) if t.get("exit_at")
    ]
    today = [t for t in closed if _ist(t["exit_at"]) >= day_start]
    month = [t for t in closed if _ist(t["exit_at"]) >= month_start]

    unrealized = 0.0
    exposure = 0.0
    if mode is None:
        positions = await ledger.get_open_positions(venue=venue)
        for symbol, position in positions.items():
            exposure += abs(position.quantity * position.avg_price)
            mark = mark_prices.get(symbol)
            if mark is not None:
                unrealized += position.quantity * (mark - position.avg_price)
        open_count = len(positions)
        open_equity = sum(p.realized_pnl for p in positions.values()) + unrealized
    else:
        open_trades = await ledger.get_trades(status="OPEN", limit=2000, venue=venue, mode=mode)
        for trade in open_trades:
            exposure += trade["quantity"] * trade["entry_price"]
            mark = mark_prices.get(trade["symbol"])
            if mark is not None:
                sign = 1 if trade["side"] == "BUY" else -1
                unrealized += sign * trade["quantity"] * (mark - trade["entry_price"])
        open_count = len(open_trades)
        open_equity = unrealized

    realized_today = sum(t["realized_pnl"] for t in today)
    realized_month = sum(t["realized_pnl"] for t in month)
    month_wins = [t for t in month if t["realized_pnl"] > 0]

    entered_today = [
        t for t in await ledger.get_trades(limit=2000, venue=venue, mode=mode)
        if t.get("entry_at") and _ist(t["entry_at"]) >= day_start
    ]

    return {
        "today": {
            "realized": realized_today,
            "unrealized": unrealized,
            "trades": len(today),
            "wins": len([t for t in today if t["realized_pnl"] > 0]),
            "losses": len([t for t in today if t["realized_pnl"] < 0]),
            "turnover": sum(t["quantity"] * t["entry_price"] for t in entered_today),
        },
        "month": {
            "realized": realized_month,
            "trades": len(month),
            "win_rate": len(month_wins) / len(month) if month else 0.0,
            "best": max((t["realized_pnl"] for t in month), default=0.0),
            "worst": min((t["realized_pnl"] for t in month), default=0.0),
        },
        "open": {
            "positions": open_count,
            "exposure": exposure,
            "equity": open_equity,
        },
    }


# ---------------------------------------------------------------------------
# Scorecard: the track record a strategy is judged on before real money.
# Every figure is net of charges (realized_pnl - costs): a strategy that only
# wins before brokerage and taxes does not win.
# ---------------------------------------------------------------------------

def _profit_factor(nets: list[float]) -> Optional[float]:
    """Gross winnings over gross losses. None when there are no losing
    trades (undefined, not infinitely good) or no trades at all."""
    losses = -sum(n for n in nets if n < 0)
    if not losses:
        return None
    return sum(n for n in nets if n > 0) / losses


def _max_drawdown(nets: list[float]) -> float:
    """Deepest peak-to-trough fall of the running total, in rupees (>= 0)."""
    total = peak = worst = 0.0
    for net in nets:
        total += net
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def _summary(nets: list[float]) -> dict:
    wins = sum(1 for n in nets if n > 0)
    return {
        "trades": len(nets),
        "wins": wins,
        "win_rate": wins / len(nets) if nets else 0.0,
        "net": sum(nets),
        "profit_factor": _profit_factor(nets),
        "max_drawdown": _max_drawdown(nets),
    }


async def compute_scorecard(
    ledger: LedgerStore, venue: Optional[Venue], account_size: float, mode: Optional[str] = None,
) -> dict:
    closed = sorted(
        (t for t in await ledger.get_trades(status="CLOSED", limit=5000, venue=venue, mode=mode) if t.get("exit_at")),
        key=lambda t: t["exit_at"],
    )

    days: dict[str, dict] = {}
    by_strategy: dict[str, list[float]] = {}
    costs = 0.0
    for trade in closed:
        cost = trade.get("costs") or 0.0
        net = (trade.get("realized_pnl") or 0.0) - cost
        costs += cost
        day = _ist(trade["exit_at"]).date().isoformat()
        row = days.setdefault(day, {"day": day, "pnl": 0.0, "trades": 0, "wins": 0})
        row["pnl"] += net
        row["trades"] += 1
        row["wins"] += net > 0
        by_strategy.setdefault(trade.get("strategy") or "unattributed", []).append(net)

    daily = list(days.values())
    totals = _summary([day["pnl"] for day in daily])
    trade_level = _summary([n for nets in by_strategy.values() for n in nets])
    return {
        "venue": venue,
        "account_size": account_size,
        "days": daily,
        "strategies": sorted(
            ({"strategy": name, **_summary(nets)} for name, nets in by_strategy.items()),
            key=lambda s: s["net"], reverse=True,
        ),
        "totals": {
            **trade_level,
            # Drawdown is measured on the day-by-day running total, the way
            # the account would actually have felt it.
            "max_drawdown": totals["max_drawdown"],
            "max_drawdown_pct": totals["max_drawdown"] / account_size * 100 if account_size else None,
            "return_pct": trade_level["net"] / account_size * 100 if account_size else None,
            "costs": costs,
            "trading_days": len(daily),
            "winning_days": totals["wins"],
            "best_day": max(daily, key=lambda d: d["pnl"]) if daily else None,
            "worst_day": min(daily, key=lambda d: d["pnl"]) if daily else None,
            "first_day": daily[0]["day"] if daily else None,
            "last_day": daily[-1]["day"] if daily else None,
        },
    }
