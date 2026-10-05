"""User facts: one user's portfolio, positions, journal, learning, strategy
record and game plan. Every read filters by the `user_id` passed in."""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from backend.ai.facts import fact
from backend.engine.session import IST

MAX_HOLDINGS, MAX_TRIPS = 40, 30
HOLDING_KEYS = ("symbol", "kind", "sector", "quantity", "avg_price", "value", "pnl", "pnl_pct", "weight_pct",
                "verdict", "reason_codes", "score", "note", "nifty_pnl_pct")
TRIP_KEYS = ("symbol", "kind", "direction", "quantity", "entry_price", "exit_price", "pnl", "day", "tags", "note")


@fact("portfolio", "The user's analysed long-term holdings: totals, benchmark, concentration, the review plan, and "
      "each holding's value, P&L, weight and review verdict. Pass symbol for one holding in detail; account "
      "all/ai/mine.", user=True, source="portfolio snapshot")
async def portfolio(db, redis, user_id, symbol: Optional[str] = None,
                    account: Literal["all", "ai", "mine"] = "all") -> dict:
    from backend.chat.context import plan_names
    from backend.journal.store import JournalStore
    from backend.portfolio.service import latest_snapshot
    from backend.prefs import PrefsStore

    snap = await latest_snapshot(db, user_id)
    if not snap:
        return {"error": "No portfolio has been analysed yet. The user can tap Analyse now on the Portfolio page."}
    if account != "all":
        from backend.brokers.roles import brokers_for
        from backend.portfolio.service import _nifty, scorecard_for

        roles = (await PrefsStore(db).get(user_id)).get("broker_roles") or {}
        snap = scorecard_for(snap, brokers_for(roles, account), await JournalStore(db).list_trades(user_id),
                             await _nifty())
    holdings = snap.get("holdings", [])
    if symbol:
        match = [h for h in holdings if h["symbol"].upper() == symbol.upper()]
        if not match:
            return {"error": f"{symbol} is not among the user's holdings."}
        return {**{k: match[0].get(k) for k in HOLDING_KEYS}, "health": match[0].get("health")}
    return {
        # as_of is when the portfolio was analysed, not when it was read: stale holdings must look stale.
        "account": account, "as_of": snap["at"], "totals": snap.get("totals"), "benchmark": snap.get("benchmark"),
        "concentration": snap.get("concentration"), "plan": snap.get("plan"),
        "sell_or_trim": plan_names(snap.get("plan"), "sell"), "add": plan_names(snap.get("plan"), "add"),
        "holdings": [{k: h.get(k) for k in HOLDING_KEYS if k != "note"} for h in holdings[:MAX_HOLDINGS]],
    }


@fact("positions", "The user's open engine positions (paper or live venue): symbol, quantity, average price.",
      user=True, source="ledger")
async def positions(db, redis, user_id, venue: Literal["paper", "live"] = "paper") -> dict:
    from backend.engine.persistence import LedgerStore

    open_ = await LedgerStore(db, user_id=user_id).get_open_positions(venue=venue)
    return {"venue": venue, "positions": [{"symbol": s, "quantity": p.quantity, "avg_price": p.avg_price}
                                          for s, p in sorted(open_.items())]}


@fact("journal", "The user's own trade journal (imported from their broker): round trips, P&L by day, behaviour "
      "patterns (incl. news at entry) and all-time costs. period today/week/month/all.", user=True,
      source="journal")
async def journal(db, redis, user_id, period: Literal["today", "week", "month", "all"] = "month",
                  symbol: Optional[str] = None, account: Literal["all", "ai", "mine"] = "all") -> dict:
    from backend.journal import mirror
    from backend.journal.accounts import brokers_of, filter_trades
    from backend.journal.insights import build_insights
    from backend.journal.news import attach_news
    from backend.journal.roundtrips import build_round_trips, daily_pnl
    from backend.journal.store import JournalStore
    from backend.prefs import PrefsStore

    prefs = await PrefsStore(db).get(user_id)
    trades = filter_trades(await JournalStore(db).list_trades(user_id),
                           brokers_of(prefs.get("broker_roles") or {}, account))
    trips = build_round_trips(trades)
    all_time = mirror.costs(trades, trips, prefs["account_size"])
    today = datetime.now(timezone.utc).astimezone(IST).date()
    since = {"today": today, "week": today - timedelta(days=7), "month": today.replace(day=1)}.get(period)
    if since:
        trips = [t for t in trips if t.get("day") and t["day"] >= since.isoformat()]
    if symbol:
        trips = [t for t in trips if t["symbol"].upper().startswith(symbol.upper())]
    closed = [t for t in trips if t.get("pnl") is not None]
    return {
        "account": account, "period": period, "closed": len(closed),
        "pnl_gross": round(sum(t["pnl"] for t in closed), 2), "wins": sum(t["pnl"] > 0 for t in closed),
        "by_day": daily_pnl(trips)[-31:], "round_trips": [{k: t.get(k) for k in TRIP_KEYS} for t in trips[-MAX_TRIPS:]],
        "patterns": build_insights(await attach_news(db, trips))[:5],
        # All-time, estimated: charges taken, P&L after them, trade rate vs SEBI's 500/yr line.
        "costs_all_time": all_time,
    }


@fact("learning", "What the engine learned from the user's paper trades: paused strategies, raised floors, regime "
      "skips, results by setup, recent changes and re-tunes.", user=True, source="learning")
async def learning(db, redis, user_id) -> dict:
    from backend.learning.report import snapshot
    from backend.portfolio.service import _nifty

    return await snapshot(db, user_id, await _nifty(), datetime.now(timezone.utc))


@fact("strategy_library", "The strategy library: what each strategy is for (style, regimes, needs, best/avoid) and "
      "its record for this user (backtest gate, paper record, learned state, results by trend and reason).",
      user=True, source="strategy library")
async def strategy_library(db, redis, user_id, mode: Optional[Literal["INTRADAY", "LONGTERM"]] = None) -> dict:
    from backend.learning.library import catalog
    from backend.portfolio.service import _nifty

    return {"strategies": await catalog(db, user_id, await _nifty(), mode=mode)}


@fact("game_plan", "Today's AI game plan for the user's intraday account (allowed stocks and strategies, risk, "
      "rationale) and its revisions.", user=True, source="trade_plans")
async def game_plan(db, redis, user_id) -> dict:
    from backend.plan import store

    day = datetime.now(timezone.utc).astimezone(IST).date()
    versions = await store.versions(db, user_id, day)
    return {"plan": await store.current(redis, user_id, day),
            "versions": [{k: v.get(k) for k in ("version", "at", "trigger", "rationale")} for v in versions]}
