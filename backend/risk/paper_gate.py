"""The paper gate: a strategy may run live for a user only once it has
also earned it on that user's own paper book, on top of the backtest gate
(backend/risk/backtest_gate.py) -- never instead of it. A backtest says the
idea worked on history; the paper record says it works now, filled at live
prices, net of charges, in this account's own sizing.

Every figure is net of charges and comes from the same closed paper trades
the Paper scorecard shows (backend/analytics.py).
"""

from backend.analytics import _ist, _summary
from backend.engine.persistence import venue_filter

MIN_PAPER_DAYS = 20
MIN_PAPER_TRADES = 30
MIN_PAPER_PROFIT_FACTOR = 1.3
# Deepest fall of the strategy's running net P&L, as % of account_size.
MAX_PAPER_DRAWDOWN_PCT = 5.0


def paper_record(trades: list[dict], account_size: float) -> dict:
    """`trades` are one strategy's closed paper trades. Each check says what
    is needed and what the record has, so the UI can show the gap."""
    trades = sorted((t for t in trades if t.get("exit_at")), key=lambda t: t["exit_at"])
    nets = [(t.get("realized_pnl") or 0.0) - (t.get("costs") or 0.0) for t in trades]
    summary = _summary(nets)
    days = len({_ist(t["exit_at"]).date() for t in trades})
    drawdown_pct = summary["max_drawdown"] / account_size * 100 if account_size else 0.0
    pf = summary["profit_factor"]
    checks = [
        {"rule": "days", "need": MIN_PAPER_DAYS, "have": days, "ok": days >= MIN_PAPER_DAYS},
        {"rule": "trades", "need": MIN_PAPER_TRADES, "have": len(nets), "ok": len(nets) >= MIN_PAPER_TRADES},
        {"rule": "net", "need": 0, "have": round(summary["net"], 2), "ok": summary["net"] > 0},
        # No losing trade at all leaves profit factor undefined, not failing.
        {"rule": "profit_factor", "need": MIN_PAPER_PROFIT_FACTOR,
         "have": round(pf, 2) if pf is not None else None,
         "ok": bool(nets) and (pf is None or pf >= MIN_PAPER_PROFIT_FACTOR)},
        {"rule": "max_drawdown_pct", "need": MAX_PAPER_DRAWDOWN_PCT, "have": round(drawdown_pct, 2),
         "ok": drawdown_pct <= MAX_PAPER_DRAWDOWN_PCT},
    ]
    return {"checks": checks, "passed": all(c["ok"] for c in checks)}


async def paper_records(db, user_id: str, strategy_names: list[str], account_size: float) -> dict[str, dict]:
    docs = await db["paper_trades"].find({
        "user_id": user_id, "status": "CLOSED", "strategy": {"$in": strategy_names},
        **venue_filter("paper"),
    }).to_list(length=None)
    return {
        name: paper_record([d for d in docs if d.get("strategy") == name], account_size)
        for name in strategy_names
    }
