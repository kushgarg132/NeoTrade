"""Results and ex-dividend dates of the symbols users hold, and the dividends
those holdings paid. Market-wide reference data: no user_id."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.datalayer.bars import ticker, today_ist
from backend.engine.session import IST

logger = logging.getLogger(__name__)

EVENTS = "corporate_events"
META = "corporate_events_meta"


def _day(v) -> str:
    return (v.date() if hasattr(v, "date") else v).isoformat()


def _fetch_sync(tkr: str) -> list[dict]:
    """The only network call: calendar (next results / ex-dividend) plus the
    last 3 years of paid dividends."""
    import yfinance as yf

    t = yf.Ticker(tkr)
    out = []
    cal = t.calendar or {}
    for d in cal.get("Earnings Date") or []:
        out.append({"kind": "results", "date": _day(d), "amount": None})
    if cal.get("Ex-Dividend Date"):
        out.append({"kind": "ex_dividend", "date": _day(cal["Ex-Dividend Date"]), "amount": None})
    cutoff = (datetime.now() - timedelta(days=3 * 366)).date()
    for ts, amount in t.dividends.items():
        if ts.date() >= cutoff:
            out.append({"kind": "ex_dividend", "date": ts.date().isoformat(), "amount": float(amount)})
    return out


async def refresh(db, symbols: set[str], today: date) -> int:
    """Fetches symbols not yet checked today; returns how many succeeded."""
    done = 0
    for symbol in sorted(symbols):
        if await db[META].find_one({"symbol": symbol, "checked": today.isoformat()}):
            continue
        try:
            rows = await asyncio.to_thread(_fetch_sync, ticker(symbol))
        except Exception:
            logger.warning("corp events: %s failed", symbol, exc_info=True)
            continue
        now = datetime.now(timezone.utc)
        for r in rows:
            key = {"symbol": symbol, "kind": r["kind"], "date": r["date"]}
            fields = {"source": "yfinance", "fetched_at": now}
            if r["amount"] is None:  # a calendar row must not erase a known amount
                await db[EVENTS].update_one(key, {"$set": fields, "$setOnInsert": {"amount": None}}, upsert=True)
            else:
                await db[EVENTS].update_one(key, {"$set": {**fields, "amount": r["amount"]}}, upsert=True)
        await db[META].update_one({"symbol": symbol}, {"$set": {"checked": today.isoformat()}}, upsert=True)
        done += 1
    return done


async def loop(db, redis, now: Optional[datetime] = None) -> None:
    from backend.portfolio.service import mine_holdings

    held: set[str] = set()
    for user_id in await db.portfolio_snapshots.distinct("user_id"):
        held |= set(await mine_holdings(db, user_id))
    n = await refresh(db, held, today_ist(now))
    logger.info("ingest corp_events: %d/%d symbol(s)", n, len(held))


async def upcoming(db, symbols, today: date, days: int) -> list[dict]:
    lo, hi = today.isoformat(), (today + timedelta(days=days)).isoformat()
    cur = db[EVENTS].find({"symbol": {"$in": list(symbols)}, "date": {"$gte": lo, "$lte": hi}}, {"_id": 0})
    return sorted(await cur.to_list(None), key=lambda e: (e["date"], e["symbol"]))


async def dividends_received(db, trades: list[dict], symbol: str, until: date, ratio: int = 1) -> list[dict]:
    """Dividends the journal's holding earned: quantity held before each
    ex-date (buys minus sells) times the per-share amount. yfinance amounts are
    split-adjusted, so `ratio` (lots.split_ratio) scales the journal quantity."""
    mine = [(t["traded_at"].astimezone(IST).date().isoformat(), float(t["quantity"]) * ratio * (1 if t["side"] == "BUY" else -1))
            for t in trades if t["symbol"] == symbol]
    cur = db[EVENTS].find({"symbol": symbol, "kind": "ex_dividend", "amount": {"$ne": None},
                           "date": {"$lte": until.isoformat()}}, {"_id": 0})
    out = []
    for e in sorted(await cur.to_list(None), key=lambda e: e["date"]):
        qty = sum(q for d, q in mine if d < e["date"])
        if qty > 1e-9:
            out.append({"date": e["date"], "per_share": e["amount"], "qty": qty, "amount": qty * e["amount"]})
    return out
