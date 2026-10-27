"""P&L aggregates for the dashboard cards.

Boundaries are IST, the market's own day: a trade closed at 23:00 IST is
today's trade, and truncating in UTC would file it under yesterday. Trades
come out of `paper_trades` (round trips), not fills, so "3 trades today"
means three round trips rather than however many executions they took.
"""

from datetime import datetime, timezone
from typing import Optional

from backend.autopilot.fence import PARKED
from backend.core.models import Venue
from backend.engine.persistence import LedgerStore, trade_net
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
    # Net of charges, the figure Practice shows; older rows without `costs` count none.
    costs = lambda trades: sum(t.get("costs") or 0.0 for t in trades)  # noqa: E731
    realized_all = sum(t["realized_pnl"] for t in closed)
    month_wins = [t for t in month if trade_net(t) > 0]

    entered_today = [
        t for t in await ledger.get_trades(limit=2000, venue=venue, mode=mode)
        if t.get("entry_at") and _ist(t["entry_at"]) >= day_start
    ]

    return {
        "today": {
            "realized": realized_today,
            "unrealized": unrealized,
            "trades": len(today),
            "wins": len([t for t in today if trade_net(t) > 0]),
            "losses": len([t for t in today if trade_net(t) < 0]),
            "turnover": sum(t["quantity"] * t["entry_price"] for t in entered_today),
            "costs": costs(today),
            "net": realized_today - costs(today),
        },
        "month": {
            "realized": realized_month,
            "trades": len(month),
            "win_rate": len(month_wins) / len(month) if month else 0.0,
            "best": max((t["realized_pnl"] for t in month), default=0.0),
            "worst": min((t["realized_pnl"] for t in month), default=0.0),
            "costs": costs(month),
            "net": realized_month - costs(month),
        },
        # ponytail: capped at the 2000 newest closed trades, like every figure here.
        "all_time": {
            "realized": realized_all,
            "costs": costs(closed),
            "net": realized_all - costs(closed),
            "trades": len(closed),
            "wins": len([t for t in closed if trade_net(t) > 0]),
        },
        "open": {
            "positions": open_count,
            "exposure": exposure,
            "equity": open_equity,
        },
    }


async def compute_live_pnl(db, user_id: str, marks: dict[str, float], mode: Optional[str] = None,
                           marks_fn=None) -> dict:
    """Real-money figures as two separate books, never summed: `mine` (orders
    placed on the user's own account, `<uid>:mine`) and `ai` (the live
    autopilot's `<uid>:autopilot`). Fills land in those namespaces, not in
    `<uid>`, so reading `<uid>` with venue=live always came back empty.
    `marks` may lack symbols held only live; the gap is fetched here."""
    from backend.autopilot.service import ledger_user
    from backend.engine.persistence import mine_book
    from backend.marks import mark_prices

    marks_fn = marks_fn or mark_prices
    books = {"mine": LedgerStore(db, user_id=mine_book(user_id)),
             "ai": LedgerStore(db, user_id=ledger_user(user_id))}
    held = {s for b in books.values() for s in await b.get_open_positions(venue="live")}
    marks = {**marks, **(await marks_fn(db, [s for s in held if s not in marks]) if held - marks.keys() else {})}
    return {name: await compute_pnl(b, marks, venue="live", mode=mode) for name, b in books.items()}


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


def open_by_strategy(open_trades: list[dict], marks: dict[str, float]) -> dict[str, dict]:
    """strategy -> {open, unrealized}: open positions at the mark, gross (their entry charges are already in
    `costs` and the exit's are not known yet); a position with no mark counts at 0. Pure."""
    out: dict[str, dict] = {}
    for t in open_trades:
        row = out.setdefault(t.get("strategy") or "unattributed", {"open": 0, "unrealized": 0.0})
        row["open"] += 1
        mark, entry, qty = marks.get(t.get("symbol")), t.get("entry_price"), t.get("quantity") or 0.0
        if mark and entry:
            row["unrealized"] += (mark - entry) * qty * (1 if t.get("side", "BUY") == "BUY" else -1)
    return {k: {**v, "unrealized": round(v["unrealized"], 2)} for k, v in out.items()}


def nifty_same_money(trades: list[dict], points: list[dict]) -> dict[str, float]:
    """strategy -> what each trade's rupees would have made in NIFTY over that trade's own days (the close
    before its entry day to the close of its exit day, or the latest close while open): the bar a stock
    picker has to clear, since buying the index costs next to nothing. `points` are NIFTY closes
    ({date, close}, oldest first). A trade outside the points' range is left out. Pure."""
    from bisect import bisect_left, bisect_right

    dates, closes = [p["date"] for p in points], [p["close"] for p in points]
    out: dict[str, float] = {}
    for t in trades:
        if not t.get("entry_at") or not t.get("entry_price"):
            continue
        a = bisect_left(dates, _ist(t["entry_at"]).date().isoformat()) - 1
        b = bisect_right(dates, _ist(t["exit_at"]).date().isoformat()) - 1 if t.get("exit_at") else len(dates) - 1
        if a < 0 or b <= a:
            continue
        side = 1 if t.get("side", "BUY") == "BUY" else -1
        move = side * t["entry_price"] * (t.get("quantity") or 0.0) * (closes[b] / closes[a] - 1)
        name = t.get("strategy") or "unattributed"
        out[name] = out.get(name, 0.0) + move
    return out


async def compute_scorecard(
    ledger: LedgerStore, venue: Optional[Venue], account_size: float, mode: Optional[str] = None,
    marks: Optional[dict[str, float]] = None, nifty_points: Optional[list[dict]] = None,
) -> dict:
    """Closed trades net of charges, per day and per strategy; with `marks` (symbol -> price) each strategy
    also carries its open positions at market (`open`, `unrealized`, `total` = net + unrealized), so a
    strategy holding losers no longer reads as flat until it sells. With `nifty_points` each strategy and
    the totals carry `nifty` (the same rupees in NIFTY over the same days) and `vs_nifty` = total - nifty."""
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
    open_trades = await ledger.get_trades(status="OPEN", limit=5000, venue=venue, mode=mode) if marks is not None else []
    opens = open_by_strategy(open_trades, marks) if marks is not None else {}
    index = nifty_same_money(closed + open_trades, nifty_points) if nifty_points else None
    for name in opens:
        by_strategy.setdefault(name, [])
    zero = {"open": 0, "unrealized": 0.0}

    def vs(total: float, name: Optional[str] = None) -> dict:
        if index is None:
            return {}
        n = sum(index.values()) if name is None else index.get(name, 0.0)
        return {"nifty": round(n, 2), "vs_nifty": round(total - n, 2)}

    rows = [{"strategy": name, "parked": name in PARKED, **_summary(nets), **opens.get(name, zero),
             "total": sum(nets) + opens.get(name, zero)["unrealized"]} for name, nets in by_strategy.items()]
    return {
        "venue": venue,
        "account_size": account_size,
        "days": daily,
        "strategies": sorted(({**r, **vs(r["total"], r["strategy"])} for r in rows), key=lambda s: s["total"], reverse=True),
        "totals": {
            **trade_level,
            # Drawdown is measured on the day-by-day running total, the way
            # the account would actually have felt it.
            "max_drawdown": totals["max_drawdown"],
            "max_drawdown_pct": totals["max_drawdown"] / account_size * 100 if account_size else None,
            "return_pct": trade_level["net"] / account_size * 100 if account_size else None,
            "costs": costs,
            "open": sum(o["open"] for o in opens.values()),
            "unrealized": round(sum(o["unrealized"] for o in opens.values()), 2),
            "trading_days": len(daily),
            "winning_days": totals["wins"],
            "best_day": max(daily, key=lambda d: d["pnl"]) if daily else None,
            "worst_day": min(daily, key=lambda d: d["pnl"]) if daily else None,
            "first_day": daily[0]["day"] if daily else None,
            "last_day": daily[-1]["day"] if daily else None,
            **vs(trade_level["net"] + sum(o["unrealized"] for o in opens.values())),
        },
    }
