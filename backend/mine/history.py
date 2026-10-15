"""The user's own account day by day (`mine_daily`): what it was worth, what
went in, and what the same rupees would be worth in NIFTY -- plus the XIRR
of both. Quantities come from the journal; shares the journal never saw
(held before its history began) enter as one lot at the earliest snapshot's
average price and mark the curve `partial`. Mutual funds are left out (their
NAVs are not in daily_bars) and flagged `funds_excluded`.
"""

import logging
from bisect import bisect_left
from datetime import date, datetime
from typing import Optional

from backend.datalayer import bars
from backend.engine.session import IST
from backend.mine.lots import mine_trades

logger = logging.getLogger(__name__)

COLLECTION = "mine_daily"


# ------------------------------------------------------------------ XIRR


def xirr(flows: list[tuple[date, float]]) -> Optional[float]:
    """Annual rate (a fraction) that zeroes the flows' present value; money
    in negative, money out positive. None without both signs, or no root."""
    if not any(v > 0 for _, v in flows) or not any(v < 0 for _, v in flows):
        return None
    t0 = min(d for d, _ in flows)
    years = [((d - t0).days / 365.0, v) for d, v in flows]

    def f(r):
        return sum(v / (1 + r) ** t for t, v in years)

    def df(r):
        return sum(-t * v / (1 + r) ** (t + 1) for t, v in years)

    r = 0.1
    for _ in range(100):
        slope = df(r)
        if not slope:
            break
        step = f(r) / slope
        r -= step
        if r <= -0.99 or r > 10:
            break
        if abs(step) < 1e-10:
            return r
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-10:
            return (lo + hi) / 2
    return None


# ------------------------------------------------------------------ inputs


def _held(snap: dict, funds: set, mine) -> dict[str, list]:
    """symbol -> [quantity, cost] of a snapshot's own-account stocks."""
    held: dict[str, list] = {}
    for h in snap.get("raw_holdings") or []:
        if h.get("kind", "STOCK") == "MF" or h["symbol"] in funds or (mine and h.get("broker") not in mine):
            continue
        row = held.setdefault(h["symbol"], [0.0, 0.0])
        row[0] += h["quantity"]
        row[1] += h["quantity"] * h["avg_price"]
    return held


async def _inputs(db, user_id: str) -> dict:
    """events: (IST date, symbol, signed qty, price), oldest first -- the
    journal's mine trades plus the unknown-date gap lot. Funds excluded.
    A sell of shares bought before the journal is clipped to what the journal
    holds (as `lots._fifo`), and a split or bonus the journal never saw
    (`lots.split_ratio`) scales every event of that symbol, since daily_bars
    are split-adjusted."""
    from backend.brokers.roles import brokers_for
    from backend.mine.lots import open_lots, split_ratio
    from backend.portfolio.service import latest_snapshot
    from backend.prefs import PrefsStore

    latest = await latest_snapshot(db, user_id) or {}
    funds = {h["symbol"] for h in latest.get("raw_holdings") or [] if h.get("kind") == "MF"}
    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    trades = [t for t in await mine_trades(db, user_id) if t["symbol"] not in funds]
    ratio = {s: split_ratio(open_lots(trades, s), q, c / q if q else None)
             for s, (q, c) in _held(latest, funds, mine).items()}
    events, running = [], {}
    for t in sorted(trades, key=lambda t: t["traded_at"]):
        s, r = t["symbol"], ratio.get(t["symbol"], 1)
        q = float(t["quantity"]) * r
        if t["side"] != "BUY":
            q = -min(q, running.get(s, 0.0))
            if q > -1e-9:
                continue
        running[s] = running.get(s, 0.0) + q
        events.append((t["traded_at"].astimezone(IST).date(), s, q, float(t["price"]) / r))

    gap_events = []
    first = await db["portfolio_snapshots"].find({"user_id": user_id}).sort("at", 1).limit(1).to_list(length=1)
    first_day = None
    if first:
        snap = first[0]
        first_day = snap["at"].astimezone(IST).date() if snap["at"].tzinfo else snap["at"].date()
        for symbol, (qty, cost) in _held(snap, funds, mine).items():
            journal = sum(q for d, s, q, _ in events if s == symbol and d <= first_day)
            if qty - journal > 1e-9:
                gap_events.append((first_day, symbol, qty - journal, cost / qty))
    events = sorted(events + gap_events, key=lambda e: e[0])
    start = min(e[0] for e in events) if events else first_day
    return {"events": events, "partial": bool(gap_events),
            "funds": bool(funds), "start": start}


async def _compute(db, user_id: str, today: date) -> list[dict]:
    """One row per NIFTY trading day from the first event to `today`."""
    data = await _inputs(db, user_id)
    events, start = data["events"], data["start"]
    if not start:
        return []
    symbols = sorted({e[1] for e in events})
    # today=start: staleness is meaningless for history (a sold stock's bars end long ago).
    frames = await bars.read(db, [bars.NIFTY, *symbols], start, today=start)
    if bars.NIFTY not in frames:
        return []
    nifty = {i.date(): float(c) for i, c in frames[bars.NIFTY]["close"].items() if i.date() <= today}
    closes = {s: {i.date(): float(c) for i, c in frames[s]["close"].items()} for s in symbols if s in frames}
    days = sorted(d for d in nifty if d >= start)
    by_day: dict[int, list] = {}
    for e in events:  # a trade on a non-trading day lands on the next session
        i = bisect_left(days, e[0])
        if i < len(days):
            by_day.setdefault(i, []).append(e)

    qty: dict[str, float] = {}
    carry = {s: next(p for _, sym, _, p in events if sym == s) for s in symbols}
    units = invested = 0.0
    rows = []
    last_nifty = None
    for i, day in enumerate(days):
        flow = 0.0
        for _, sym, q, price in by_day.get(i, []):
            qty[sym] = qty.get(sym, 0.0) + q
            flow += q * price
        for s in symbols:
            carry[s] = closes.get(s, {}).get(day, carry[s])
        last_nifty = nifty.get(day, last_nifty)
        units += flow / last_nifty
        invested += flow
        by_symbol = {s: {"qty": qty[s], "value": round(qty[s] * carry[s], 2)}
                     for s in symbols if qty.get(s, 0) > 1e-9}
        rows.append({
            "user_id": user_id, "date": day.isoformat(), "flow": round(flow, 2), "invested": round(invested, 2),
            "value": round(sum(v["value"] for v in by_symbol.values()), 2),
            "nifty_value": round(units * last_nifty, 2), "by_symbol": by_symbol, "partial": data["partial"],
        })
    return rows


async def _store(db, rows: list[dict]) -> None:
    """Upserts only the rows that changed: one read, then a write per difference
    (not bulk_write: see instruments/master.py on the test fake)."""
    if not rows:
        return
    stored = {d["date"]: d async for d in db[COLLECTION].find({"user_id": rows[0]["user_id"]}, {"_id": 0})}
    for row in rows:
        if stored.get(row["date"]) != row:
            await db[COLLECTION].update_one({"user_id": row["user_id"], "date": row["date"]}, {"$set": row}, upsert=True)


# ------------------------------------------------------------------ writes


async def backfill(db, user_id: str, today: date) -> int:
    rows = await _compute(db, user_id, today)
    await _store(db, rows)
    return len(rows)


async def write_all(db, now: datetime) -> int:
    """The 16:00 pass: every user's whole curve, recomputed and upserted, so a
    journal import landing later (older buys, a missed day) fixes the past.
    One replay over daily_bars per user; only changed rows are written."""
    # ponytail: full replay per user per day; store running totals if this gets slow.
    written = 0
    for user_id in sorted(await db["portfolio_snapshots"].distinct("user_id")):
        try:
            written += await backfill(db, user_id, bars.today_ist(now))
        except Exception as exc:
            logger.exception("mine history failed for %s: %s", user_id, exc)
    return written


# ------------------------------------------------------------------ reads


async def series(db, user_id: str, since: Optional[date]) -> list[dict]:
    query = {"user_id": user_id}
    if since:
        query["date"] = {"$gte": since.isoformat()}
    docs = await db[COLLECTION].find(query).sort("date", 1).to_list(length=None)
    for d in docs:
        d.pop("_id", None)
    return docs


async def returns(db, user_id: str, today: date, extra_flows: list[tuple[date, float]] = ()) -> dict:
    """XIRR of the account and of the same rupees in NIFTY, up to the newest
    stored row. `extra_flows` are positive cash-backs (dividends), the
    account's only."""
    data = await _inputs(db, user_id)
    rows = await series(db, user_id, None)
    out = {"xirr": None, "nifty_xirr": None, "from_date": data["start"].isoformat() if data["start"] else None,
           "partial": data["partial"], "funds_excluded": data["funds"]}
    if not rows:
        return out
    end = date.fromisoformat(rows[-1]["date"])
    # Flows after the newest row have no value in it yet (m1).
    flows = [(d, -q * p) for d, _, q, p in data["events"] if d <= end]
    out["xirr"] = xirr(flows + [(end, rows[-1]["value"])] + [f for f in extra_flows if f[0] <= end])
    out["nifty_xirr"] = xirr(flows + [(end, rows[-1]["nifty_value"])])
    return out
