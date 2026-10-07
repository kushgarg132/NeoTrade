"""Closing approved long-term paper positions at their stop or target.

A swing proposal also carries `max_hold_days` (out after that many trading
days) and `trail_atr` (the stop rises to the highest close since entry minus
k x the 14-day ATR, from daily_bars, and never falls; kept on the trade as
`trail_stop`). exit_reasons() applies all of it for this book and the
autopilot's.

A long-term proposal is approved together with its stop and target; nothing
else ever sells it. This checks every open long-term paper long against the
proposal that opened it and, when the mark has crossed either level, sells
the whole position on paper at that mark -- the same fill path an approval
uses (service.fill_on_paper). Paper only: a live position is the broker's.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from backend.components.quant.indicators import Indicators
from backend.core.models import Order, Side
from backend.datalayer import bars
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.marks import mark_prices
from backend.suggestions.service import fill_on_paper
from backend.ws.publish import publisher_for

logger = logging.getLogger(__name__)


def breach(mark: float, stop: Optional[float], target: Optional[float]) -> Optional[str]:
    """Which level a long position's mark has crossed, if any. Stop wins a
    tie: a mark at or under the stop is a loss to cut, whatever the target."""
    if stop is not None and mark <= stop:
        return "stop"
    if target is not None and mark >= target:
        return "target"
    return None


def _ist_date(at: datetime) -> date:
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(IST).date()


def held_too_long(entry_at: datetime, now: datetime, max_hold_days: int) -> bool:
    """Weekdays strictly after the entry's IST date, up to and including
    today's, reached `max_hold_days` (NSE holidays count as trading days)."""
    start = _ist_date(entry_at) + timedelta(days=1)
    return int(np.busday_count(start, _ist_date(now) + timedelta(days=1))) >= max_hold_days


def trail_level(highest_close: float, atr: float, k: float) -> float:
    return highest_close - k * atr


def _trail_from_bars(df: pd.DataFrame, entry: date, k: float) -> Optional[float]:
    atr = Indicators.atr(df["high"], df["low"], df["close"]).iloc[-1]
    closes = df["close"][df.index >= pd.Timestamp(entry)]
    if closes.empty or pd.isna(atr):
        return None
    return trail_level(float(closes.max()), float(atr), k)


async def exit_reasons(db, trades: list[dict], suggestions: dict, marks: dict, now: datetime) -> dict[str, str]:
    """trade id -> why it sells now: "stop" / "trailing stop" first, then
    "target", then "max hold". A trail that rose is saved on the trade;
    a symbol without fresh daily bars keeps its last stop."""
    trailing = [t for t in trades if (suggestions.get(t["suggestion_id"]) or {}).get("trail_atr")]
    frames = {}
    if trailing:  # 40 calendar days before the earliest entry covers the 14-bar ATR
        since = min(_ist_date(t["entry_at"]) for t in trailing) - timedelta(days=40)
        frames = await bars.read(db, {t["symbol"] for t in trailing}, since, today=_ist_date(now))
    reasons = {}
    for trade in trades:
        suggestion, mark = suggestions.get(trade["suggestion_id"]), marks.get(trade["symbol"])
        if suggestion is None or mark is None:
            continue
        stop, trail = suggestion.get("stop"), trade.get("trail_stop")
        df = frames.get(trade["symbol"])
        if suggestion.get("trail_atr") and df is not None:
            new = _trail_from_bars(df, _ist_date(trade["entry_at"]), suggestion["trail_atr"])
            if new is not None and new > max((x for x in (stop, trail) if x is not None), default=float("-inf")):
                trail = new
                await db["paper_trades"].update_one({"id": trade["id"]}, {"$set": {"trail_stop": new}})
        if trail is not None and (stop is None or trail > stop) and mark <= trail:
            reasons[trade["id"]] = "trailing stop"
        elif why := breach(mark, stop, suggestion.get("target")):
            reasons[trade["id"]] = why
        elif suggestion.get("max_hold_days") and held_too_long(trade["entry_at"], now, suggestion["max_hold_days"]):
            reasons[trade["id"]] = "max hold"
    return reasons


async def check_exits(db, user_id: str, now: Optional[datetime] = None, marks_fn=mark_prices) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    ledger = LedgerStore(db, user_id=user_id, on_change=publisher_for(user_id))
    trades = [
        t for t in await ledger.get_trades(status="OPEN", venue="paper", mode="LONGTERM", limit=1000)
        # The autopilot's paper trades share this book; it exits its own, through its fence.
        if t["side"] == "BUY" and t.get("suggestion_id") and not (t.get("strategy") or "").startswith("autopilot:")
    ]
    if not trades:
        return []

    suggestions = {
        s["id"]: s for s in await db["suggestions"].find(
            {"user_id": user_id, "id": {"$in": [t["suggestion_id"] for t in trades]}}
        ).to_list(length=None)
    }
    marks = await marks_fn(db, {t["symbol"] for t in trades})
    reasons = await exit_reasons(db, trades, suggestions, marks, now)

    closed = []
    for trade in trades:
        reason = reasons.get(trade["id"])
        if reason is None:
            continue
        mark = marks[trade["symbol"]]
        order = Order(
            id=str(uuid.uuid4()), symbol=trade["symbol"], side=Side.SELL, quantity=trade["quantity"],
            order_type="MARKET", limit_price=None, product="CNC",
            strategy_name=trade.get("strategy"), suggestion_id=trade["suggestion_id"],
        )
        await fill_on_paper(ledger, order, mark, now)
        gross = (mark - trade["entry_price"]) * trade["quantity"]
        closed.append({
            "symbol": trade["symbol"], "reason": reason, "price": mark,
            "quantity": trade["quantity"], "entry_price": trade["entry_price"], "gross_pnl": gross,
        })
        logger.info("auto-exit %s for %s at %s (%s)", trade["symbol"], user_id, mark, reason)
    return closed
