"""Score due forward records against the Picks daily-bar table (never raises into callers).

Entry/exit follow forecast/study.py::outcome: next-open entry, exit close `horizon_days` later;
intraday records enter at `ref_price` (fallback open) and exit the same day's close.
Net returns come only from lab/assumptions.py::round_trip_return; SELL scores the short side."""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.market_calendar import add_trading_days
from backend.engine.session import IST
from backend.lab.assumptions import round_trip_return

logger = logging.getLogger(__name__)

VOID_AFTER = 10  # trading days past due with no bars -> stop retrying


def _score(t: dict, record: dict, d0, intraday: bool, horizon: int) -> Optional[dict]:
    days = t["close"].index
    p = int(days.searchsorted(pd.Timestamp(d0), side="left" if intraday else "right"))
    q = p + horizon
    sym = record["symbol"]
    if q >= len(days) or sym not in t["close"].columns or (intraday and days[p].date() != d0):
        return None
    entry = record.get("ref_price") if intraday and record.get("ref_price") else t["open"][sym].iat[p]
    # intraday: NIFTY from the decision-time reference when recorded, else the day open (leaks the morning move)
    n_in = record.get("nifty_ref") if intraday and record.get("nifty_ref") else t["nifty_open"].iat[p]
    exit_, n_out = t["close"][sym].iat[q], t["nifty_close"].iat[q]
    if not (all(np.isfinite([entry, exit_, n_in, n_out])) and entry > 0):
        return None
    entry, exit_ = float(entry), float(exit_)
    net = round_trip_return(entry, exit_) if record["side"] == "BUY" else round_trip_return(exit_, entry)
    nifty = float(n_out / n_in - 1)
    return {"entry_date": days[p].date().isoformat(), "exit_date": days[q].date().isoformat(),
            "net": net, "nifty": nifty, "excess": net + nifty if record["side"] == "SELL" else net - nifty, "won": net > 0}


def outcome(t: dict, record: dict) -> Optional[dict]:
    """{entry_date, exit_date, net, nifty, excess, won}; {"void": "no bars"} once unscorable
    VOID_AFTER trading days past due; None while still waiting."""
    at = record["decided_at"]
    d0 = (at.astimezone(IST) if at.tzinfo else at).date()
    intraday = bool(record.get("intraday"))
    horizon = 0 if intraday else int(record["horizon_days"])
    res = _score(t, record, d0, intraday, horizon)
    days = t["close"].index
    if res is None and len(days):
        due = d0 if intraday else add_trading_days(d0, horizon + 1)
        if add_trading_days(due, VOID_AFTER) <= days[-1].date():
            return {"void": "no bars"}
    return res


async def score_due(db, now: datetime, t: Optional[dict] = None, store=None) -> int:
    """Score every due record that has bars; returns how many were scored. Never raises."""
    try:
        if store is None:
            from backend.forward.store import ForwardStore
            store = ForwardStore(db)
        due = await store.due(now)
        if not due:
            return 0
        if t is None:
            from backend.forecast import picks
            t = await picks.load(db, now)
        if t is None:
            return 0
        scored = 0
        for rec in due:
            try:
                out = outcome(t, rec)
                if out is not None:
                    await store.set_outcome(rec["_id"], out, now)
                    scored += "void" not in out
            except Exception as exc:
                logger.warning("forward score failed for %s: %s", rec.get("_id"), exc)
        return scored
    except Exception as exc:
        logger.exception("forward scoring failed: %s", exc)
        return 0
