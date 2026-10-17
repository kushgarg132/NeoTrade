"""/mine -- the redesigned Mine page's data: the headline and what drove it,
and the value curve against NIFTY. Everything is the user's own account
(`mine` brokers), from the journal and daily history (backend/mine/).
Later endpoints are appended below; do not reorder these."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal

import re

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.engine.session import IST
from backend.mine.thesis import SYMBOL, ThesisIn, ThesisStore

router = APIRouter(prefix="/mine", tags=["Mine"])
RANGE_DAYS = {"1M": 31, "6M": 183, "1Y": 366, "ALL": None}
TAX_FIRST_FY = 2025  # earlier FYs had other rates (15%/10%, Rs 1 lakh; changed 2024-07-23)
DRIVERS = 3


def _split(contributions: dict[str, float]) -> dict:
    """The biggest gainers and losers, up to DRIVERS each; zero is neither."""
    rows = [{"symbol": s, "contribution": round(c, 2)} for s, c in contributions.items() if abs(c) >= 0.005]
    gain = sorted((r for r in rows if r["contribution"] > 0), key=lambda r: -r["contribution"])
    loss = sorted((r for r in rows if r["contribution"] < 0), key=lambda r: r["contribution"])
    return {"top": gain[:DRIVERS], "bottom": loss[:DRIVERS]}


async def _month_contributions(user_id: str, today) -> dict[str, float]:
    """Per symbol: its value now - its value before this month began - what
    was put in this month (so a purchase is not a gain). The month's flows are
    the curve's own events (clipped sells, split-scaled, the gap lot)."""
    from backend.mine import history

    first = today.replace(day=1)
    rows = await history.series(db.db, user_id, None)
    if not rows:
        return {}
    before = [r for r in rows if r["date"] < first.isoformat()]
    start = before[-1]["by_symbol"] if before else {}
    now = rows[-1]["by_symbol"]
    last = date.fromisoformat(rows[-1]["date"])
    flows: dict[str, float] = {}
    for day, symbol, qty, price in (await history._inputs(db.db, user_id))["events"]:
        if first <= day <= last:  # a trade after the newest row is not in its value yet (as returns, m1)
            flows[symbol] = flows.get(symbol, 0.0) + qty * price
    return {s: now.get(s, {}).get("value", 0.0) - start.get(s, {}).get("value", 0.0) - flows.get(s, 0.0)
            for s in {*now, *start}}


@router.get("/history")
async def mine_history(range_: Literal["1M", "6M", "1Y", "ALL"] = Query("1Y", alias="range"),
                       user: User = Depends(get_current_user)):
    from backend.mine import history

    days = RANGE_DAYS[range_]
    since = datetime.now(timezone.utc).astimezone(IST).date() - timedelta(days=days) if days else None
    rows = await history.series(db.db, user.id, since)
    return {
        "points": [{k: r[k] for k in ("date", "value", "invested", "nifty_value")} for r in rows],
        "from_date": rows[0]["date"] if rows else None,
        "partial": any(r.get("partial") for r in rows),
    }


@router.get("/overview")
async def overview(user: User = Depends(get_current_user)):
    from backend.mine import history
    from backend.portfolio import digest
    from backend.portfolio.service import latest_snapshot

    now = datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    pulse = await digest.pulse(db.db, user.id, now)
    snapshot = await latest_snapshot(db.db, user.id)
    headline = None
    if pulse:
        from backend.mine import events
        from backend.mine.lots import mine_trades

        trades = await mine_trades(db.db, user.id)
        divs = [(date.fromisoformat(d["date"]), d["amount"])
                for sym in {t["symbol"] for t in trades}
                for d in await events.dividends_received(db.db, trades, sym, today)]
        ret = await history.returns(db.db, user.id, today, divs)
        headline = {
            **{k: pulse[k] for k in ("value", "day_change", "day_change_pct", "pnl", "pnl_pct", "as_of", "holdings_as_of")},
            "xirr": ret["xirr"], "nifty_xirr": ret["nifty_xirr"],
        }
    return {
        "headline": headline,
        "drivers": {"month": _split(await _month_contributions(user.id, today)),
                    "all": _split((pulse or {}).get("pnl_by_symbol") or {})},
        "mix": {**snapshot["concentration"],
                "count": (snapshot.get("totals") or {}).get("count", len(snapshot.get("holdings") or []))}
        if (snapshot or {}).get("concentration") else None,
    }


def _thesis_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if not re.match(SYMBOL, symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol")
    return symbol


@router.get("/thesis/{symbol}")
async def get_thesis(symbol: str, user: User = Depends(get_current_user)):
    return await ThesisStore(db.db).get(user.id, _thesis_symbol(symbol)) or {}


@router.put("/thesis/{symbol}")
async def put_thesis(symbol: str, body: ThesisIn, user: User = Depends(get_current_user)):
    return await ThesisStore(db.db).put(user.id, _thesis_symbol(symbol), body)


@router.get("/tax")
async def tax(fy: int | None = Query(None, ge=TAX_FIRST_FY, le=2100), user: User = Depends(get_current_user)):
    from backend.brokers.roles import brokers_for
    from backend.mine import tax as mine_tax
    from backend.mine.lots import mine_trades
    from backend.portfolio import service
    from backend.prefs import PrefsStore

    now = datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    snapshot = await service.latest_snapshot(db.db, user.id) or {}
    mine = brokers_for((await PrefsStore(db.db).get(user.id)).get("broker_roles") or {}, "mine")
    raw = [h for h in snapshot.get("raw_holdings") or []
           if h.get("kind", "STOCK") != "MF" and (not mine or h.get("broker") in mine)]
    priced, _ = await service.quoted(db.db, raw, now)
    held: dict[str, float] = {}
    cost: dict[str, float] = {}
    prices: dict[str, float] = {}
    for h in priced:
        held[h["symbol"]] = held.get(h["symbol"], 0.0) + h["quantity"]
        cost[h["symbol"]] = cost.get(h["symbol"], 0.0) + h["quantity"] * h["avg_price"]
        if h.get("last_price"):
            prices[h["symbol"]] = float(h["last_price"])
    avgs = {s: cost[s] / q for s, q in held.items() if q}
    return mine_tax.report(await mine_trades(db.db, user.id), held, prices,
                           fy if fy is not None else mine_tax.current_fy(today), today, avgs)


@router.get("/stock/{symbol}")
async def stock_detail(symbol: str, user: User = Depends(get_current_user)):
    from backend.mine import stock
    from backend.routers.portfolio import verdicts_visible_to

    body = await stock.detail(db.db, user.id, _thesis_symbol(symbol), datetime.now(timezone.utc),
                              await verdicts_visible_to(user))
    if body is None:
        raise HTTPException(status_code=404, detail="Not held and never traded")
    return body


# ---- Needs you (mine/actions.py). Ids hold ':' so the path converter takes the rest.
from fastapi import Path  # noqa: E402  (kept with its block: other tasks append here too)

ACTION_ID = Path(..., max_length=300)


@router.get("/actions")
async def mine_actions(user: User = Depends(get_current_user)):
    from backend.mine import actions
    from backend.portfolio.digest import verdicts_visible

    return await actions.build(db.db, user.id, datetime.now(timezone.utc), await verdicts_visible(db.db, user.id))


@router.post("/actions/{action_id:path}/dismiss")
async def dismiss_action(action_id: str = ACTION_ID, user: User = Depends(get_current_user)):
    from backend.mine import actions

    await actions.dismiss(db.db, user.id, action_id)
    return {"ok": True}


@router.post("/actions/{action_id:path}/snooze")
async def snooze_action(action_id: str = ACTION_ID, user: User = Depends(get_current_user)):
    from backend.mine import actions

    await actions.snooze(db.db, user.id, action_id, datetime.now(timezone.utc))
    return {"ok": True}
