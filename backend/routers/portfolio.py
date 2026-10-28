"""/portfolio -- the user's real long-term holdings across their connected
brokers, how they are doing, and a rule-scored verdict on each.

Verdicts are deployment-gated (AppSettingsStore.portfolio_verdicts): until
it is "all", only admins see SELL / HOLD / ADD; everyone else sees the same
facts and reasons, with a SELL shown as "review first", and no action plan. Showing verdicts to
every user needs SEBI Research Analyst registration (PRODUCT.md).
"""

import asyncio
from typing import Literal, Optional

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app_settings import AppSettingsStore
from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.portfolio.rebalance import plan_rebalance, suggest, target_gaps
from backend.portfolio.service import latest_snapshot, refresh_portfolio, with_live_prices
from backend.prefs import PrefsStore
from backend.rate_limit import allow
from backend.routers.settings import RebalanceTargets

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def mask_row(row: dict) -> dict:
    """A holding row as non-visible users see it: SELL shown as REVIEW, no score or suggestion."""
    def mask(verdict):
        return "REVIEW" if verdict in ("SELL", "REVIEW") else None

    return {**row, "verdict": mask(row.get("verdict")), "previous_verdict": mask(row.get("previous_verdict")),
            "verdict_since": None, "score": None, "suggested": None}


def present(snapshot: dict, show_verdicts: bool) -> dict:
    snapshot = {k: v for k, v in snapshot.items() if k not in ("_id", "raw_holdings")}
    snapshot["verdicts_visible"] = show_verdicts
    if show_verdicts:
        return snapshot
    snapshot["plan"] = None  # sell / add suggestions: same audience as the verdicts

    snapshot["holdings"] = [mask_row(row) for row in snapshot.get("holdings", [])]
    return snapshot


async def verdicts_visible_to(user: User) -> bool:
    return user.role == "admin" or await AppSettingsStore(db.db).get_portfolio_verdicts() == "all"


@router.get("")
async def get_portfolio(
    user: User = Depends(get_current_user),
    account: Literal["all", "ai", "mine"] = "all",
    live: bool = False,
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    """The last analysed snapshot, or 404 before the first refresh. With
    `account`, just that account's holdings (backend/brokers/roles.py). With
    `live`, repriced from the brokers now (service.with_live_prices)."""
    snapshot = await latest_snapshot(db.db, user.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No portfolio analysed yet")
    if live:
        snapshot = await with_live_prices(db.db, user.id, snapshot, credentials, db.redis)
    from backend.brokers.roles import brokers_for
    from backend.journal.store import JournalStore
    from backend.portfolio.service import _nifty, scorecard_for

    # Always re-scoped: the stored card covers the user's own account only, so
    # "all" read it as everything until the first live poll recomputed it.
    roles = (await PrefsStore(db.db).get(user.id)).get("broker_roles") or {}
    if account != "all" or snapshot.get("raw_holdings"):
        brokers = brokers_for(roles, account) if account != "all" else {h.get("broker") for h in snapshot["raw_holdings"]}
        snapshot = scorecard_for(snapshot, brokers, await JournalStore(db.db).list_trades(user.id), await _nifty(),
                                 verdicts=account != "ai")
    visible = await verdicts_visible_to(user)
    if visible:
        targets = (await PrefsStore(db.db).get(user.id))["rebalance_targets"]
        snapshot = with_suggestions(snapshot, targets)
    from backend.mine.thesis import ThesisStore
    theses = await ThesisStore(db.db).all(user.id)
    snapshot = {**snapshot, "holdings": [{**r, "thesis_target": (theses.get(r["symbol"]) or {}).get("target")}
                                         for r in snapshot.get("holdings", [])]}
    return present(snapshot, visible)


def with_suggestions(snapshot: dict, targets: dict) -> dict:
    """Each holding row's one-tap AI action (rebalance.suggest)."""
    gaps, total, _ = target_gaps(snapshot.get("holdings", []), targets)
    holdings = [{**row, "suggested": suggest(row, gaps.get(row["symbol"]), total)} for row in snapshot.get("holdings", [])]
    return {**snapshot, "holdings": holdings}


@router.post("/refresh")
async def refresh(
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    if not await allow(db.redis, f"portfolio_refresh:{user.id}", 6, 60):
        raise HTTPException(status_code=429, detail="Too many refreshes: try again in a minute")
    snapshot = await refresh_portfolio(db.db, user.id, credentials, db.redis)
    if not snapshot["holdings"] and not snapshot["errors"]:
        raise HTTPException(status_code=409, detail="Connect a broker in Settings to read your holdings.")
    return present(snapshot, await verdicts_visible_to(user))


REBALANCE_PER_MINUTE = 10


MAX_REBALANCE_CANDIDATES = 20


class RebalanceRequest(BaseModel):
    new_money: float = Field(default=0, ge=0, le=1e12, allow_inf_nan=False)
    candidates: list[str] = Field(default_factory=list, max_length=MAX_REBALANCE_CANDIDATES)
    targets: Optional[RebalanceTargets] = None


def _closes_sync(symbols: list[str]) -> dict[str, float]:
    data = yf.download([f"{s}.NS" for s in symbols], period="5d", interval="1d", progress=False, group_by="ticker")
    prices = {}
    for symbol in symbols:
        try:
            frame = data[f"{symbol}.NS"] if len(symbols) > 1 else data
            close = frame["Close"].dropna()
            if len(close):
                prices[symbol] = float(close.iloc[-1])
        except Exception:
            continue  # no price: the symbol is dropped
    return prices


async def _closes(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    return await asyncio.to_thread(_closes_sync, symbols)


PRESELECT = 5  # AI picks pre-ticked under the conviction rule


async def _candidate_symbols(user: User, held: set[str]) -> list[tuple[str, str, Optional[float]]]:
    """(symbol, source, score): the user's watchlist, then -- where verdicts
    are visible -- open, unexpired AI longterm BUY picks, best score first."""
    watch = await db.db["watchlist"].find_one({"user_id": user.id}) or {}
    found = [(s, "watchlist", None) for s in dict.fromkeys(watch.get("symbols") or []) if s not in held]
    if await verdicts_visible_to(user):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        cursor = db.db["suggestions"].find(
            {"user_id": user.id, "status": "PENDING", "mode": "LONGTERM", "side": "BUY",
             "$or": [{"expires_at": None}, {"expires_at": {"$exists": False}}, {"expires_at": {"$gt": now}}]},
            {"symbol": 1, "score": 1, "strategy": 1, "status": 1, "mode": 1})
        from backend.risk.paper_gate import for_mine
        picks: dict[str, float] = {}
        for doc in await for_mine(db.db, user.id, await cursor.to_list(length=200)):
            symbol, score = doc.get("symbol"), (doc.get("score") or {}).get("final")
            if symbol and symbol not in held and (symbol not in picks or (score or 0) > picks[symbol]):
                picks[symbol] = score or 0.0
        # A name both watched and picked is the AI's pick: it keeps its score.
        found = [c for c in found if c[0] not in picks]
        found += [(s, "ai", score) for s, score in sorted(picks.items(), key=lambda kv: -kv[1])]
    return found


@router.get("/rebalance/candidates")
async def rebalance_candidates(user: User = Depends(get_current_user)):
    """Names the user may bring into a rebalance: their watchlist, plus open
    AI longterm picks where verdicts are visible (the SEBI gate above)."""
    snapshot = await latest_snapshot(db.db, user.id)
    held = {r["symbol"] for r in (snapshot or {}).get("holdings", [])}
    symbols = [c for c in await _candidate_symbols(user, held)]
    prices = await _closes([s for s, _, _ in symbols])
    out, picked = [], 0
    for symbol, source, score in symbols:
        if symbol not in prices:
            continue
        preselect = source == "ai" and picked < PRESELECT
        picked += preselect
        out.append({"symbol": symbol, "price": prices[symbol], "source": source, "score": score, "preselect": preselect})
    return out


async def _prepare(request: RebalanceRequest, user: User, all_candidates: bool = False) -> dict:
    """Everything a plan needs, priced today and scoped to the user's own
    account. `all_candidates`: every allowed name (up to the request limit),
    not just the ticked ones -- the AI list weighs them all."""
    snapshot = await latest_snapshot(db.db, user.id)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="Refresh your portfolio first")
    review = snapshot  # the review's own rows (health, verdict, note) and plan, before re-scoping
    from backend.brokers.roles import brokers_for
    from backend.core.clock import SystemClock
    from backend.engine.session import IST
    from backend.journal.store import JournalStore
    from backend.portfolio.scorecard import open_lots
    from backend.portfolio.service import quoted, scorecard_for

    # Held stocks priced like the candidates (today's quotes), not at the
    # snapshot's own days-old prices.
    now = SystemClock().now()
    raw = snapshot.get("raw_holdings") or []
    if raw:
        raw, _ = await quoted(db.db, raw, now, snapshot.get("at"))
        snapshot = {**snapshot, "raw_holdings": raw}
    prefs = await PrefsStore(db.db).get(user.id)
    targets = request.targets.model_dump() if request.targets else prefs["rebalance_targets"]
    if targets.get("rule") == "conviction" and not await verdicts_visible_to(user):
        raise HTTPException(status_code=403, detail="Conviction targets are not available on this account")
    trades = await JournalStore(db.db).list_trades(user.id)
    # Trades go to the user's own account, so only its holdings are rebalanced:
    # the AI account's book is never mixed in (backend/brokers/roles.py).
    mine = brokers_for(prefs.get("broker_roles") or {}, "mine")
    if mine or raw:
        snapshot = scorecard_for(snapshot, mine or {h.get("broker") for h in raw}, trades, [])
    if mine:
        trades = [t for t in trades if t.get("broker") in mine]
    held = {r["symbol"] for r in snapshot.get("holdings", [])}
    allowed = {s: (source, score) for s, source, score in await _candidate_symbols(user, held)}
    wanted = [s for s in dict.fromkeys(request.candidates) if s in allowed]
    if all_candidates:
        wanted = list(dict.fromkeys(wanted + list(allowed)))[:MAX_REBALANCE_CANDIDATES]
    prices = await _closes(wanted)
    candidates = [{"symbol": s, "price": prices[s], "kind": "STOCK", "sector": None,
                   "source": allowed[s][0], "score": allowed[s][1]} for s in wanted if s in prices]
    return {"snapshot": snapshot, "review": review, "candidates": candidates, "targets": targets, "ticked": set(request.candidates),
            "lots": {s: open_lots(trades, s) for s in held}, "today": now.astimezone(IST).date()}


async def _results_dates(symbols) -> dict[str, str]:
    """Next results date within RESULTS_DAYS per symbol, read through the fact layer."""
    from backend.ai.facts.market import next_results
    from backend.portfolio.ai_rebalance import RESULTS_DAYS

    symbols = sorted(set(symbols))
    if not symbols:
        return {}
    return (await next_results(db.db, db.redis, None, symbols=symbols, days=RESULTS_DAYS)).get("dates", {})


def _with_results(plan: dict, dates: dict) -> dict:
    """Each trade row carries `next_results` (ISO date or None) for the sheet."""
    return {**plan, "trades": [{**t, "next_results": dates.get(t["symbol"])} for t in plan["trades"]]}


@router.post("/rebalance")
async def rebalance(request: RebalanceRequest, user: User = Depends(get_current_user)):
    """Trades that move the book toward its targets. Nothing is placed: each
    trade opens a pre-filled ticket the user confirms."""
    if not await allow(db.redis, f"rebalance:{user.id}", REBALANCE_PER_MINUTE, 60):
        raise HTTPException(status_code=429, detail="Too many rebalance runs: try again in a minute")
    p = await _prepare(request, user)
    out = plan_rebalance(p["snapshot"].get("holdings", []), p["candidates"], p["targets"], request.new_money,
                         p["lots"], p["today"])
    out = _with_results(out, await _results_dates(t["symbol"] for t in out["trades"]))
    return {**out, "stale_since": p["snapshot"].get("stale_since")}


REBALANCE_AI_PER_MINUTE = 3


@router.post("/rebalance/ai")
async def rebalance_ai(request: RebalanceRequest, user: User = Depends(get_current_user)):
    """The AI's final list (portfolio/ai_rebalance.py): its target per stock,
    clamped to the caps and planned by the same `plan_rebalance`, beside the
    formula's plan. Same audience as the verdicts. Nothing is placed."""
    from backend.portfolio.ai_rebalance import ai_targets, clamp_targets, news_context

    if not await verdicts_visible_to(user):
        raise HTTPException(status_code=403, detail="The AI rebalance is not available on this account")
    if not await allow(db.redis, f"rebalance-ai:{user.id}", REBALANCE_AI_PER_MINUTE, 60):
        raise HTTPException(status_code=429, detail="Too many AI rebalance runs: try again in a minute")
    p = await _prepare(request, user, all_candidates=True)
    snapshot, targets, holdings = p["snapshot"], p["targets"], p["snapshot"].get("holdings", [])
    ticked = [c for c in p["candidates"] if c["symbol"] in p["ticked"]]
    formula = plan_rebalance(holdings, ticked, targets, request.new_money, p["lots"], p["today"])
    full = p["review"]
    context = {r["symbol"]: r for r in full.get("holdings", [])}
    symbols = list(dict.fromkeys([r["symbol"] for r in holdings] + [c["symbol"] for c in p["candidates"]]))
    dates = await _results_dates(symbols)
    news = await news_context(db.db, db.redis, symbols, dates)
    answer = await ai_targets(holdings, context, p["candidates"], targets, request.new_money, formula,
                              full.get("plan"), p["lots"], p["today"], news=news)
    if answer is None:
        raise HTTPException(status_code=502, detail="The AI could not build a list just now: try again")
    sector_of = {r["symbol"]: (r.get("sector") if r.get("kind") == "STOCK" else None) for r in holdings}
    sector_of.update({c["symbol"]: None for c in p["candidates"]})
    picked = clamp_targets(answer["targets"], sector_of, targets)
    chosen = [c for c in p["candidates"] if picked.get(c["symbol"], 0) > 0]
    plan = plan_rebalance(holdings, chosen, {**targets, "overrides": picked}, request.new_money, p["lots"], p["today"])
    plan = _with_results(plan, dates)
    return {"plan": {**plan, "stale_since": snapshot.get("stale_since")}, "targets": picked,
            "reasons": {s: r for s, r in answer["reasons"].items() if s in picked}, "summary": answer["summary"]}
