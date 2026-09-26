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
    venue: Optional[Venue] = None,
) -> dict:
    """`venue` narrows every figure to one book (paper or live); None keeps
    the combined view."""
    now = _ist(now or datetime.now(timezone.utc))
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    closed = [
        t for t in await ledger.get_trades(status="CLOSED", limit=2000, venue=venue) if t.get("exit_at")
    ]
    today = [t for t in closed if _ist(t["exit_at"]) >= day_start]
    month = [t for t in closed if _ist(t["exit_at"]) >= month_start]

    positions = await ledger.get_open_positions(venue=venue)
    unrealized = 0.0
    exposure = 0.0
    for symbol, position in positions.items():
        exposure += abs(position.quantity * position.avg_price)
        mark = mark_prices.get(symbol)
        if mark is not None:
            unrealized += position.quantity * (mark - position.avg_price)

    realized_today = sum(t["realized_pnl"] for t in today)
    realized_month = sum(t["realized_pnl"] for t in month)
    month_wins = [t for t in month if t["realized_pnl"] > 0]

    entered_today = [
        t for t in await ledger.get_trades(limit=2000, venue=venue)
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
            "positions": len(positions),
            "exposure": exposure,
            "equity": sum(p.realized_pnl for p in positions.values()) + unrealized,
        },
    }
