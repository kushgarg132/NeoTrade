"""Read tools for the chat. Built per message with the caller's user_id in a
closure, so the model can never ask for someone else's data: no tool takes
a user id. Outputs are compact JSON, trimmed to what an answer needs."""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, Union

from langchain_core.tools import StructuredTool

from backend.agents.tools import fetch_news_tool, fetch_price_history_tool, fetch_stock_info_tool, resolve_symbol_tool
from backend.analytics import compute_scorecard
from backend.chat.context import LIMIT_KEYS, plan_names
from backend.engine.persistence import LedgerStore
from backend.engine.session import IST
from backend.guardrails.store import GuardrailStore
from backend.journal.insights import build_insights
from backend.journal.roundtrips import build_round_trips, daily_pnl
from backend.journal.store import JournalStore
from backend.portfolio.service import latest_snapshot
from backend.prefs import PrefsStore
from backend.risk.kill_switch import KillSwitchStore
from backend.runs import RunStore, run_summary
from backend.suggestions.store import SuggestionStore

MAX_HOLDINGS, MAX_TRIPS, MAX_PROPOSALS = 40, 30, 20
MAX_ROWS, MAX_CHARS = 100, 15000

# query_my_data's allowlist. Per-user collections are always filtered to the
# caller; shared ones hold market reference data, no user's. Anything not
# listed -- broker_credentials, alert_channels (bot token), refresh_tokens,
# users, app_settings -- is unreachable by construction.
USER_DATA = {
    "portfolio_snapshots": "every portfolio analysis over time (at, totals, holdings, plan, concentration, brokers, errors)",
    "journal_trades": "real broker fills (symbol, side, quantity, price, traded_at, broker, exchange)",
    "journal_opens": "days the user opened their journal (day)",
    "journal_notes": "the user's journal notes and tags",
    "suggestions": "every engine proposal ever (symbol, side, mode, quantity, entry_ref, stop, target, score, "
                   "reason_codes, ai_thesis, status, created_at, decided_at, reason)",
    "paper_trades": "paper round trips (symbol, side, mode, entry/exit price and time, realized_pnl, costs, status, "
                    "suggestion_id, void_reason)",
    "paper_positions": "paper positions per run (symbol, quantity, avg_price, realized_pnl, unrealized_pnl, product)",
    "paper_orders": "paper orders (symbol, side, quantity, order_type, limit_price, product, status, run_id)",
    "paper_fills": "paper fills (symbol, side, quantity, price, costs, timestamp, run_id)",
    "trading_runs": "every engine run (run_id, mode, status, started_at, stopped_at, error, universe, params)",
    "chat_actions": "action cards prepared in chat (kind, summary, params, status, result, created_at)",
    "guardrail_events": "guardrail breaches by day",
    "user_prefs": "all of the user's settings and switches",
    "watchlist": "the user's watchlist symbols",
}
SHARED_DATA = {
    "stock_health": "per-symbol health scores the portfolio rules use",
    "strategy_backtests": "backtest results per strategy",
    "instrument_sectors": "sector of each instrument",
}
_HIDDEN = {"_id", "user_id"}
_BANNED_OPERATORS = {"$where", "$function", "$accumulator"}  # run JavaScript on the server
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _safe_filter(value):
    """Refuse server-side JavaScript; turn ISO datetime strings into datetimes,
    which is how *_at / timestamp fields are stored."""
    if isinstance(value, dict):
        bad = _BANNED_OPERATORS & set(value)
        if bad:
            raise ValueError(f"{', '.join(sorted(bad))} is not allowed")
        return {k: _safe_filter(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_filter(v) for v in value]
    if isinstance(value, str) and _ISO_DATETIME.match(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return value
    return value


def _json(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def read_tools(db, redis, user_id: str) -> list:
    async def get_portfolio(symbol: Optional[str] = None) -> str:
        snap = await latest_snapshot(db, user_id)
        if not snap:
            return "No portfolio has been analysed yet. The user can tap Analyse now on the Portfolio page."
        keep = ("symbol", "kind", "sector", "quantity", "avg_price", "value", "pnl", "pnl_pct", "weight_pct",
                "verdict", "reason_codes", "score", "note", "nifty_pnl_pct")
        holdings = snap.get("holdings", [])
        if symbol:
            match = [h for h in holdings if h["symbol"].upper() == symbol.upper()]
            if not match:
                return f"{symbol} is not among the user's holdings."
            return _json({**{k: match[0].get(k) for k in keep}, "health": match[0].get("health")})
        return _json({
            "as_of": snap["at"], "totals": snap.get("totals"), "benchmark": snap.get("benchmark"),
            "concentration": snap.get("concentration"), "plan": snap.get("plan"),
            "sell_or_trim": plan_names(snap.get("plan"), "sell"), "add": plan_names(snap.get("plan"), "add"),
            "holdings": [{k: h.get(k) for k in keep if k != "note"} for h in holdings[:MAX_HOLDINGS]],
        })

    async def get_journal(period: Literal["today", "week", "month", "all"] = "month", symbol: Optional[str] = None) -> str:
        trips = build_round_trips(await JournalStore(db).list_trades(user_id))
        today = datetime.now(timezone.utc).astimezone(IST).date()
        since = {"today": today, "week": today - timedelta(days=7), "month": today.replace(day=1)}.get(period)
        if since:
            trips = [t for t in trips if t.get("day") and t["day"] >= since.isoformat()]
        if symbol:
            trips = [t for t in trips if t["symbol"].upper().startswith(symbol.upper())]
        closed = [t for t in trips if t.get("pnl") is not None]
        keep = ("symbol", "kind", "direction", "quantity", "entry_price", "exit_price", "pnl", "day", "tags", "note")
        return _json({
            "period": period, "closed": len(closed), "pnl_gross": round(sum(t["pnl"] for t in closed), 2),
            "wins": sum(t["pnl"] > 0 for t in closed), "by_day": daily_pnl(trips)[-31:],
            "round_trips": [{k: t.get(k) for k in keep} for t in trips[-MAX_TRIPS:]],
            "patterns": build_insights(trips)[:5],
        })

    async def get_paper() -> str:
        from backend.risk.backtest_gate import BacktestGateStore
        from backend.risk.paper_gate import paper_records
        from backend.strategies.registry import build_default_strategies

        prefs = await PrefsStore(db).get(user_id)
        ledger = LedgerStore(db, user_id=user_id)
        card = await compute_scorecard(ledger, "paper", prefs["account_size"])
        names = [s.spec.name for s in build_default_strategies(universe=["PLACEHOLDER"], option_universe=["PLACEHOLDER"])]
        records = await paper_records(db, user_id, names, prefs["account_size"])
        gate = BacktestGateStore(db)
        progress = {}
        for name in names:
            backtest = await gate.latest(name)
            progress[name] = {
                "backtest_passed": bool(backtest and backtest["passed"]),
                "paper_passed": records[name]["passed"], "live_switch": name in prefs["live_strategies"],
            }
        positions = await ledger.get_open_positions(venue="paper")
        tripped = await KillSwitchStore(db).is_tripped(user_id, datetime.now(timezone.utc).astimezone(IST).date())
        return _json({
            "scorecard": {"totals": card["totals"], "strategies": card["strategies"], "last_days": card["days"][-5:]},
            "open_positions": [{"symbol": s, "quantity": p.quantity, "avg_price": p.avg_price} for s, p in positions.items()],
            "running": [run_summary(r) for r in await RunStore(db).list_active(user_id)],
            "auto_paper_intraday": prefs.get("auto_paper_intraday"),
            "auto_paper_longterm": prefs.get("auto_paper_longterm"),
            "kill_switch": {"tripped": bool(tripped), "reason": (tripped or {}).get("reason")},
            "go_live_progress": progress,
        })

    async def get_decisions(status: Literal["pending", "decided"] = "pending", symbol: Optional[str] = None) -> str:
        items = await SuggestionStore(db).list(user_id, limit=200)
        items = [s for s in items if (s["status"] == "PENDING") == (status == "pending")]
        if symbol:
            items = [s for s in items if s["symbol"].upper() == symbol.upper()]
        keep = ("id", "symbol", "side", "mode", "quantity", "entry_ref", "stop", "target", "notional", "score",
                "reason_codes", "ai_thesis", "status", "option_contract", "created_at", "expires_at")
        return _json([{k: s.get(k) for k in keep} for s in items[:MAX_PROPOSALS]])

    async def get_limits() -> str:
        prefs = await PrefsStore(db).get(user_id)
        alerts = await GuardrailStore(db).events_for(user_id, datetime.now(timezone.utc).astimezone(IST).date())
        return _json({
            **{k: prefs.get(k) for k in LIMIT_KEYS},
            "cooldown_after_losses": prefs.get("cooldown_after_losses"), "cooldown_minutes": prefs.get("cooldown_minutes"),
            "account_size": prefs.get("account_size"), "max_exposure": prefs.get("max_exposure"),
            "alerts_today": [{"title": a.get("title"), "detail": a.get("detail")} for a in alerts],
        })

    async def query_my_data(collection: str, filter: Optional[dict] = None, sort_by: Optional[str] = None,
                            descending: bool = True, limit: int = 20, fields: Optional[list[str]] = None) -> str:
        if collection not in USER_DATA and collection not in SHARED_DATA:
            return f"Unknown collection. Readable: {', '.join([*USER_DATA, *SHARED_DATA])}."
        try:
            query = _safe_filter(filter or {})
        except ValueError as exc:
            return str(exc)
        if collection in USER_DATA:
            # $and, not a merge: the model's filter can never widen past this user.
            query = {"$and": [query, {"user_id": user_id}]}
        projection = {f: 1 for f in fields} if fields else None
        cursor = db[collection].find(query, projection)
        if sort_by:
            cursor = cursor.sort(sort_by, -1 if descending else 1)
        rows = await cursor.limit(max(1, min(limit, MAX_ROWS))).to_list(length=MAX_ROWS)
        rows = [{k: v for k, v in r.items() if k not in _HIDDEN} for r in rows]
        text = _json({"matched": await db[collection].count_documents(query), "returned": len(rows), "rows": rows})
        # ponytail: hard cut keeps the context bounded; the model narrows with fields/filter/limit.
        return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "… (truncated: pass fields or a smaller limit)"

    async def explain_index(ticker: str) -> str:
        from backend.research.index_move import explain_index_move

        result = await explain_index_move(ticker, ticker)
        return _json({k: result.get(k) for k in ("analysis", "session_date", "headlines") if k in result})

    own = [
        StructuredTool.from_function(coroutine=get_portfolio, name="get_portfolio", description=(
            "The user's long-term holdings from their brokers: totals, each holding's value, gain, weight, rule "
            "verdict (SELL/HOLD/ADD) and reasons, the AI action plan, sector mix. Pass symbol for one holding in full.")),
        StructuredTool.from_function(coroutine=get_journal, name="get_journal", description=(
            "The user's real broker trades as round trips: gross P&L by day, recent trips, and habit patterns. "
            "period is today, week, month or all; symbol narrows to one scrip.")),
        StructuredTool.from_function(coroutine=get_paper, name="get_paper", description=(
            "The paper-trading engine: net scorecard per strategy, open paper positions, running engine runs, "
            "the daily auto-run switch, the kill switch, and how far each strategy is from going live.")),
        StructuredTool.from_function(coroutine=get_decisions, name="get_decisions", description=(
            "Proposals from the engine with their id, terms (entry, stop, target, quantity), score and thesis. "
            "status pending or decided; symbol narrows to one scrip. Use the id with propose_approve or propose_decline.")),
        StructuredTool.from_function(coroutine=get_limits, name="get_limits", description=(
            "The user's own limits (daily loss limit, per-trade cap, trades per day, cooldown, switches) and "
            "today's guardrail alerts.")),
        StructuredTool.from_function(coroutine=query_my_data, name="query_my_data", description=(
            "Read any of the user's NeoTrade data when the other tools do not cover it (history, older records, "
            "counts, raw fields). Read-only and always limited to this user. collection is one of:\n"
            + "\n".join(f"- {k}: {v}" for k, v in {**USER_DATA, **SHARED_DATA}.items())
            + "\nfilter is a MongoDB query, e.g. {\"symbol\": \"INFY\", \"realized_pnl\": {\"$lt\": 0}}; give "
            "times as ISO datetimes (\"2026-10-01T00:00:00+05:30\"). sort_by a field (newest first by default), "
            f"limit up to {MAX_ROWS}, fields to return only some. 'matched' is the full count.")),
        StructuredTool.from_function(coroutine=explain_index, name="explain_index", description=(
            "Why an index moved in its latest session, e.g. ^NSEI for NIFTY 50 or ^NSEBANK for BANK NIFTY.")),
    ]
    return own + [fetch_news_tool, fetch_stock_info_tool, fetch_price_history_tool, resolve_symbol_tool]
