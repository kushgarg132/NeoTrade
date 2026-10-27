"""Exit levels for long-term positions, and alerts for the user's own.

A swing proposal also carries `max_hold_days` (out after that many trading
days) and `trail_atr` (the stop rises to the highest close since entry minus
k x the 14-day ATR, from daily_bars, and never falls; kept on the trade as
`trail_stop`). exit_reasons() applies all of it for this book and the
autopilot's.

A long-term proposal comes with its stop and target, priced off its
reference close (`entry_ref`); they are applied at the same distance from
the trade's actual fill (`anchored`), so a gap at the open does not leave a
stop k x ATR from a price nobody paid. The autopilot sells
its own positions at them (autopilot/service.py::check_exits); on the
user's own account check_exits() only alerts -- the user places the sell.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.market_calendar import HOLIDAYS
from backend.strategies.indicators import Indicators
from backend.datalayer import bars
from backend.engine.persistence import LedgerStore, mine_book
from backend.engine.session import IST
from backend.marks import mark_prices

logger = logging.getLogger(__name__)


def breach(mark: float, stop: Optional[float], target: Optional[float]) -> Optional[str]:
    """Which level a long position's mark has crossed, if any. Stop wins a
    tie: a mark at or under the stop is a loss to cut, whatever the target."""
    if stop is not None and mark <= stop:
        return "stop"
    if target is not None and mark >= target:
        return "target"
    return None


def anchored(level: Optional[float], entry_ref: Optional[float], fill: Optional[float]) -> Optional[float]:
    """A level priced off the proposal's reference close, moved to the fill at the same distance
    (fill - k x ATR for a stop). Without a reference or a fill the stored level stands."""
    if level is None or not entry_ref or not fill:
        return level
    return level + (fill - entry_ref)


def _ist_date(at: datetime) -> date:
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(IST).date()


def held_too_long(entry_at: datetime, now: datetime, max_hold_days: int) -> bool:
    """NSE trading days strictly after the entry's IST date, up to and including
    today's, reached `max_hold_days`."""
    start = _ist_date(entry_at) + timedelta(days=1)
    return int(np.busday_count(start, _ist_date(now) + timedelta(days=1), holidays=list(HOLIDAYS))) >= max_hold_days


def max_hold_due(entry_at: datetime, now: datetime, max_hold_days: int) -> bool:
    """The backtest sells at the close of the due day: on it, only from 15:15 IST (the last check);
    any later day, any time."""
    if not held_too_long(entry_at, now, max_hold_days):
        return False
    if held_too_long(entry_at, now - timedelta(days=1), max_hold_days):
        return True
    t = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(IST)
    return (t.hour, t.minute) >= (15, 15)


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
        try:
            frames = await bars.read(db, {t["symbol"] for t in trailing}, since, today=_ist_date(now))
        except Exception:  # stops and targets still run on the stored levels
            logger.exception("exit check: daily bars unreadable, trails kept as stored")
    reasons = {}
    for trade in trades:
        suggestion, mark = suggestions.get(trade["suggestion_id"]), marks.get(trade["symbol"])
        if suggestion is None or mark is None:
            continue
        ref, fill = suggestion.get("entry_ref"), trade.get("entry_price")
        stop, trail = anchored(suggestion.get("stop"), ref, fill), trade.get("trail_stop")
        df = frames.get(trade["symbol"])
        if suggestion.get("trail_atr") and df is not None:
            try:  # one bad trade's trail must not cancel the others' exits
                new = _trail_from_bars(df, _ist_date(trade["entry_at"]), suggestion["trail_atr"])
                if new is not None and new > max((x for x in (stop, trail) if x is not None), default=float("-inf")):
                    await db["paper_trades"].update_one({"id": trade["id"]}, {"$set": {"trail_stop": new}})
                    trail = new
            except Exception:
                logger.exception("exit check: trail for %s failed, keeping %s", trade["symbol"], trail or stop)
        if trail is not None and (stop is None or trail > stop) and mark <= trail:
            reasons[trade["id"]] = "trailing stop"
        elif why := breach(mark, stop, anchored(suggestion.get("target"), ref, fill)):
            reasons[trade["id"]] = why
        elif suggestion.get("max_hold_days") and max_hold_due(trade["entry_at"], now, suggestion["max_hold_days"]):
            reasons[trade["id"]] = "max hold"
    return reasons


async def check_exits(db, user_id: str, now: Optional[datetime] = None, marks_fn=mark_prices) -> list[dict]:
    """Exit alerts for the user's own account: each open long the app placed
    there from a proposal (`<user>:mine`, engine/persistence.py::mine_book)
    whose mark crossed that proposal's stop, target or trailing stop, or that
    reached max_hold_days. Nothing is sold -- the user decides; each reason
    alerts once per trade. A trade whose stock has left the user's holdings
    since it was bought (sold in the broker's own app) is closed as `sold`."""
    from backend.portfolio.service import latest_snapshot, mine_holdings

    now = now or datetime.now(timezone.utc)
    ledger = LedgerStore(db, user_id=mine_book(user_id))
    trades = [t for t in await ledger.get_trades(status="OPEN", mode="LONGTERM", limit=1000)
              if t["side"] == "BUY" and t.get("suggestion_id")]
    if not trades:
        return []

    snapshot = await latest_snapshot(db, user_id)
    seen_at = _aware(snapshot["at"]) if snapshot else None
    held = await mine_holdings(db, user_id)
    open_ = []
    for trade in trades:
        # Only a read from a later day: a same-day delivery buy is not in the
        # broker's holdings yet (it shows under positions until settled).
        if seen_at is not None and _ist_date(seen_at) > _ist_date(trade["entry_at"]) and trade["symbol"] not in held:
            await db["paper_trades"].update_one(
                {"id": trade["id"]}, {"$set": {"status": "CLOSED", "exit_at": now, "exit_reason": "sold",
                          # Inferred from a holdings snapshot, not a fill: shown as such in the UI.
                          "closed_by": "inferred_from_holdings"}})
            continue
        open_.append(trade)
    if not open_:
        return []

    suggestions = {
        s["id"]: s for s in await db["suggestions"].find(
            {"user_id": user_id, "id": {"$in": [t["suggestion_id"] for t in open_]}}
        ).to_list(length=None)
    }
    marks = await marks_fn(db, {t["symbol"] for t in open_})
    reasons = await exit_reasons(db, open_, suggestions, marks, now)

    alerts = []
    for trade in open_:
        reason = reasons.get(trade["id"])
        if reason is None or reason in (trade.get("alerted") or []):
            continue
        await db["paper_trades"].update_one({"id": trade["id"]}, {"$addToSet": {"alerted": reason}})
        mark = marks[trade["symbol"]]
        alerts.append({
            "symbol": trade["symbol"], "reason": reason, "price": mark,
            "quantity": trade["quantity"], "entry_price": trade["entry_price"],
            "gross_pnl": (mark - trade["entry_price"]) * trade["quantity"],
        })
    return alerts


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
