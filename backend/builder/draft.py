"""The weekly drafting job (docs/superpowers/specs/2026-10-07-strategy-builder-design.md §3).

Friday night the model drafts up to three block specs from the week's plans, scorecards, the
library, the worst setups and every earlier draft. Each is validated, then backtested on a year
of 5-minute history; it becomes `active` (paper) only if it passes the backtest gate, is
net-positive over the last 90 days alone, and clears the deflated Sharpe counting every draft
ever tested. The model never decides; these three checks do.

Swing drafts (docs/superpowers/specs/2026-10-07-swing-builder-design.md §3-4) get their own prompt,
vocabulary and trial count, and test on 3 years of stored daily bars (after 300 days of warm-up):
the gate, the last 180 days net-positive, the deflated Sharpe, and beating an equal-weight
buy-and-hold of the same stocks over the same 3 years.

CPU-heavy, so the daily pass starts it as its own low-priority process (`python -m backend.builder`).
"""
import asyncio
import json
import logging
import math
import re
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.builder import store
from backend.builder.validate import describe, slugify, validate_spec
from backend.core.models import Side
from backend.engine.execution.costs import calculate_indian_costs
from backend.engine.session import IST
from backend.factor.validate import deflated_sharpe
from backend.learning.retune import ACCOUNT, MIN_DSR, _at, _daily, _sharpe
from backend.risk.backtest_gate import (LOOKBACK_DAYS, MAX_DRAWDOWN, MIN_PROFIT_FACTOR, MIN_TRADES, MIN_WINDOW_DAYS,
                                        BacktestGateStore, passes_gate)
from backend.strategies.blocks.vocab import EXITS, FILTERS, SETUPS, SWING_EXITS, SWING_FILTERS, SWING_SETUPS
from backend.suggestions.notify import notify
from backend.system import jobs

logger = logging.getLogger(__name__)

LOCK = "builder:lock"
LOCK_TTL = 6 * 3600
MAX_DRAFTS = 3
MAX_ACTIVE = 5
YEAR, HOLDOUT, PAUSED_DAYS = timedelta(days=LOOKBACK_DAYS), timedelta(days=90), 30
HORIZONS = ("intraday", "swing")
SWING_SPAN, SWING_WARMUP, SWING_HOLDOUT = timedelta(days=3 * 365), timedelta(days=300), timedelta(days=180)
MIN_SWING_SYMBOLS = 30  # fewer with stored bars: swing drafts wait


def _rupees(v: float) -> str:
    return f"{'−' if v < 0 else '+' if v > 0 else ''}₹{abs(v):,.0f}"


def _vocabulary(horizon: str = "intraday") -> str:
    def show(spec) -> str:
        if not spec:
            return "true (flag)"
        if spec[0] == "HH:MM":
            return f"HH:MM {spec[1]}..{spec[2]}"
        return " | ".join(spec) if isinstance(spec[0], str) else f"{spec[0]}..{spec[1]} step {spec[2]}"

    lines = []
    kinds = (SETUPS, FILTERS, EXITS) if horizon == "intraday" else (SWING_SETUPS, SWING_FILTERS, SWING_EXITS)
    for kind, blocks in zip(("setup", "filter", "exit"), kinds):
        for name, params in blocks.items():
            lines.append(f"{kind} {name}: " + "; ".join(f"{k} {show(v)}" for k, v in params.items()))
    return "\n".join(lines) + "\n(regime_is regimes: any non-empty list of the choices)"


def _dump(fact_out: dict, key: str) -> str:
    if "error" in fact_out:
        return f"unavailable ({fact_out['error']})"
    return json.dumps(fact_out.get(key), default=str, ensure_ascii=False) if fact_out.get(key) else "none yet"


async def _prompt(db, redis, admin_id, horizon: str = "intraday") -> tuple[str, str]:
    from backend.ai.facts import user as facts
    from backend.prompts import render

    mode = "INTRADAY" if horizon == "intraday" else "LONGTERM"
    library = await facts.strategy_library(db, redis, admin_id, mode=mode) if admin_id else {"error": "no admin"}
    common = {"vocabulary": _vocabulary(horizon), "library": _dump(library, "strategies"),
              "setups": _dump(await facts.worst_setups(db, redis, None, limit=10), "setups"),
              "drafts": _dump(await facts.built_strategies(db, redis, None, horizon=horizon), "strategies")}
    if horizon == "swing":  # the game plans and their scorecards are about intraday days
        return render("strategy_builder_swing", **common)
    return render(
        "strategy_builder", **common,
        plans=_dump(await facts.recent_plans(db, redis, None, days=5), "plans"),
        scorecards=_dump(await facts.plan_scorecards(db, redis, None, weeks=4), "scorecards"),
    )


async def _default_llm(system: str, prompt: str) -> str:
    from backend.llm import llm_service

    return await llm_service.get_completion(prompt, system_prompt=system, tier="deep", feature="learning") or ""


def _parse(text: str) -> list:
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        ideas = json.loads(match.group(0)).get("strategies") if match else None
    except (json.JSONDecodeError, AttributeError):
        ideas = None
    return [i for i in ideas if isinstance(i, dict)][:MAX_DRAFTS] if isinstance(ideas, list) else []


async def _history(db, redis, horizon: str = "intraday"):
    """(backtest, strategy kwargs) on a year of 5-minute history, or None without a source
    (or when the source or universe cannot be read: drafts then wait for next week)."""
    if horizon == "swing":
        return await _swing_history(db)
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.engine.backtest import run_backtest
    from backend.learning.retune import _Memo
    from backend.risk import gate_backtest

    try:
        _, adapter = await gate_backtest.intraday_history(db, redis)
        instruments, tokens = await gate_backtest.gate_universe(db) if adapter is not None else ([], {})
    except Exception as exc:
        logger.warning("strategy builder: no history source: %s", exc)
        return None
    if not instruments:  # no source, or an empty universe that would "fail" the gate with 0 trades
        return None
    memo = _Memo(adapter)  # one fetch per symbol, however many drafts replay it

    async def backtest(strategy, start, end, account):  # sized per draft by its owner
        return await run_backtest([strategy], memo, instruments, start=start, end=end, timeframe="5m", **account)

    kwargs = {"universe": [i.tradingsymbol for i in instruments], "symbol_for_token": tokens,
              "regime_of": await store.regime_of(db), "sector_of": nifty200_sectors()}
    return backtest, kwargs


async def _swing_history(db):
    """(backtest, strategy kwargs) on 3 years plus warm-up of the stored daily bars (no broker
    session needed), or None while fewer than MIN_SWING_SYMBOLS of the scan universe have them.
    kwargs["bars"] is what the buy-and-hold benchmark is computed from."""
    from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
    from backend.data.providers.store import StoreHistoryProvider
    from backend.datalayer import bars
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.engine.backtest import run_backtest
    from backend.learning.retune import _Memo
    from backend.risk import gate_backtest

    window = SWING_SPAN + SWING_WARMUP
    try:
        frames = await bars.read(db, ALL_SCAN_STOCKS, bars.today_ist() - window)
        enough = len(frames) >= MIN_SWING_SYMBOLS
        instruments, tokens = await gate_backtest.gate_universe(db, list(frames)) if enough else ([], {})
    except Exception as exc:
        logger.warning("strategy builder: no daily history: %s", exc)
        return None
    if len(instruments) < MIN_SWING_SYMBOLS:  # a symbol without bars is skipped, not faked
        return None
    memo = _Memo(StoreHistoryProvider(db))

    async def backtest(strategy, start, end, account):
        return await run_backtest([strategy], memo, instruments, start=start, end=end, timeframe="1d", **account)

    kwargs = {"universe": [i.tradingsymbol for i in instruments], "symbol_for_token": tokens,
              "regime_of": await store.regime_of(db, days=window.days + 300),  # + the 200-day average's own
              "sector_of": nifty200_sectors(), "bars": frames}
    return backtest, kwargs


def _since(r, cut: datetime, account_size: float):
    """`r` over the round trips opened from `cut` on: the warm-up's bars feed the indicators, its trades
    don't count. Metrics as engine/backtest.py computes them; the span starts at `cut`."""
    from backend.engine.metrics import compute_max_drawdown, compute_sharpe_ratio

    held, early, open_net, kept, trips = {}, set(), {}, [], []
    for t in r.trades:
        s = t["symbol"]
        if abs(held.get(s, 0)) < 1e-9:  # this fill opens a position
            (early.add if _at(t) < cut else early.discard)(s)
        held[s] = held.get(s, 0) + (t["quantity"] if t["side"] == Side.BUY.value else -t["quantity"])
        if s in early:
            continue
        kept.append(t)
        open_net[s] = open_net.get(s, 0.0) + t["net_pnl"]
        if abs(held[s]) < 1e-9:
            trips.append(open_net.pop(s))
    gain = sum(t["net_pnl"] for t in kept if t["net_pnl"] > 0)
    loss = -sum(t["net_pnl"] for t in kept if t["net_pnl"] < 0)
    return r.model_copy(update={
        "start_date": max(r.start_date, cut), "total_trades": len(trips),
        "win_rate": sum(p > 0 for p in trips) / len(trips) if trips else 0.0,
        "profit_factor": gain / loss if loss > 0 else 0.0, "total_pnl": sum(t["net_pnl"] for t in kept),
        "max_drawdown": compute_max_drawdown(kept, account_size),
        "sharpe_ratio": compute_sharpe_ratio(kept, account_size), "trades": kept})


def _benchmark(bars_by_symbol: dict, start: datetime, end: datetime, charges_pct: float) -> float:
    """Equal-weight buy-and-hold % over [start, end] of the symbols with a close on both its first and
    last trading day, minus one round trip of charges: what a swing strategy must beat."""
    lo, hi = (pd.Timestamp(t.astimezone(IST).date()) for t in (start, end))
    spans = [c for f in bars_by_symbol.values() if len(c := f["close"][(f.index >= lo) & (f.index <= hi)])]
    first, last = min(c.index[0] for c in spans), max(c.index[-1] for c in spans)
    rets = [c.iloc[-1] / c.iloc[0] - 1 for c in spans if c.index[0] == first and c.index[-1] == last]
    if not rets:
        raise ValueError("no symbol spans the benchmark window")
    return float(sum(rets) / len(rets) * 100 - charges_pct)


def _gate_reason(r) -> str:
    """The first failing check of passes_gate, in its order."""
    days = (r.end_date - r.start_date).days
    if days < MIN_WINDOW_DAYS:
        return f"gate: {days} days < {MIN_WINDOW_DAYS}"
    if r.total_trades < MIN_TRADES:
        return f"gate: {r.total_trades} trades < {MIN_TRADES}"
    if r.profit_factor < MIN_PROFIT_FACTOR:
        return f"gate: PF {r.profit_factor:.2f} < {MIN_PROFIT_FACTOR:g}"
    if r.max_drawdown > MAX_DRAWDOWN:
        return f"gate: DD {r.max_drawdown * 100:.0f}% > {MAX_DRAWDOWN * 100:.0f}%"
    return "gate: failed"


async def _test(db, doc: dict, backtest, kwargs: dict, now: datetime) -> tuple[str, str, dict]:
    """(status, verdict, fields) for one draft; records its gate row."""
    from backend.strategies.built import BlockStrategy

    strategy = BlockStrategy(doc["slug"], doc["spec"], kwargs.get("universe", []), kwargs.get("symbol_for_token", {}),
                             regime_of=kwargs.get("regime_of"), sector_of=kwargs.get("sector_of"),
                             thesis=doc.get("thesis") or "AI-built strategy.")
    horizon = store.horizon_of(doc)
    swing = horizon == "swing"
    end = now
    # Swing: the backtest starts with the warm-up, the checks see the 3 years after it.
    cut, holdout_days = (end - SWING_SPAN, SWING_HOLDOUT) if swing else (end - YEAR, HOLDOUT)
    start = cut - SWING_WARMUP if swing else cut
    from backend.risk.gate_backtest import backtest_account

    account = await backtest_account(db, doc.get("owner_id"))  # size like the draft's owner
    r = await backtest(strategy, start, end, account)
    if swing:
        r = _since(r, cut, account["account_size"])
    daily = _daily(r.trades, cut, end) * (ACCOUNT / account["account_size"])  # a fraction of the account that was sized
    sharpe = _sharpe(daily)
    finite = math.isfinite(sharpe) and math.isfinite(float(daily.to_numpy().sum()))  # _sharpe maps NaN to 0
    sharpe = sharpe if finite else None  # never stored: it would poison every later trial count
    history = store.history_of(doc) + ([sharpe] if finite else [])  # a re-test is a new trial
    trials = await store.trial_sharpes(db, doc.get("owner_id"), exclude=doc["slug"], horizon=horizon) + history
    holdout = [t for t in r.trades if _at(t) >= end - holdout_days]
    hold_net = round(sum(t["net_pnl"] for t in holdout), 2)
    fields = {"sharpe": sharpe, "trial_history": history, "trials": len(trials), "tested_at": now, "metrics": {
        "year": {"trades": r.total_trades, "pf": round(r.profit_factor, 2), "dd": round(r.max_drawdown, 4),
                 "net": round(r.total_pnl, 2), "win_rate": round(r.win_rate, 4)},
        "holdout": {"trades": len(holdout), "net": hold_net}}}
    if swing:
        ticket = account["per_trade_cap"] or account["account_size"]
        charges = sum(calculate_indian_costs(ticket, 1, side, "CNC") for side in (Side.BUY, Side.SELL)) / ticket * 100
        mine, buy_hold = r.total_pnl / account["account_size"] * 100, _benchmark(kwargs["bars"], cut, end, charges)
        fields["metrics"]["benchmark"] = {"strategy_pct": round(mine, 2), "buy_hold_pct": round(buy_hold, 2)}
    await BacktestGateStore(db).record(strategy.spec.name, r)
    if not finite:
        return "rejected", "non-finite Sharpe", fields
    if not passes_gate(r):
        return "rejected", _gate_reason(r), fields
    if hold_net <= 0:
        return "rejected", f"holdout: {_rupees(hold_net)} over the last {holdout_days.days} days", fields
    dsr = deflated_sharpe(daily, trials)
    if dsr < MIN_DSR:
        return "rejected", f"deflated Sharpe {dsr:.2f} < {MIN_DSR} over {len(trials)} drafts", fields
    if swing and not mine > buy_hold:
        return "rejected", f"benchmark: {mine:+.1f}% < buy-and-hold {buy_hold:+.1f}%", fields
    return "active", f"passed: PF {r.profit_factor:.2f}, deflated Sharpe {dsr:.2f} over {len(trials)} drafts", fields


async def _paper_net(db, slug: str) -> float:
    from backend.learning.attribution import net

    trades = await db["paper_trades"].find({"strategy": f"built:{slug}", "venue": {"$ne": "live"}, "status": "CLOSED"}).to_list(None)
    return sum(net(t) for t in trades)


async def _make_room(db, horizon: str = "intraday") -> list[str]:
    """At most MAX_ACTIVE AI strategies per horizon (users' own don't count): retires that horizon's
    lowest paper net across users (ties: oldest)."""
    active = [d for d in await db[store.COLLECTION].find({"status": "active", "owner_id": None})
              .sort("drafted_at", 1).to_list(None) if store.horizon_of(d) == horizon]
    if len(active) < MAX_ACTIVE:
        return []
    nets = [(await _paper_net(db, d["slug"]), i, d["slug"]) for i, d in enumerate(active)]
    worst_net, _, slug = min(nets)
    await store.set_status(db, slug, "retired", f"retired for a stronger draft: lowest paper net ({_rupees(worst_net)})")
    return [slug]


async def _retire_paused(db, admin_id, now: datetime) -> list[str]:
    """Actives the learning loop has kept paused for PAUSED_DAYS."""
    state = await db["learning_state"].find_one({"user_id": admin_id}) if admin_id else None
    retired = []
    for name, since in ((state or {}).get("paused") or {}).items():
        if not name.startswith("built:") or not isinstance(since, datetime):
            continue
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        slug = name.removeprefix("built:")
        if now - since >= timedelta(days=PAUSED_DAYS) and await db[store.COLLECTION].find_one(
                {"slug": slug, "status": "active"}):
            await store.set_status(db, slug, "retired", f"paused by the learning loop for {PAUSED_DAYS}+ days")
            retired.append(slug)
    return retired


def _unique(slug: str, taken: set) -> str:
    out, n = slug, 2
    while out in taken:
        out, n = f"{slug}-{n}", n + 1
    taken.add(out)
    return out


async def run(db, redis, now: datetime, llm=None, backtest=None) -> dict:
    """The whole weekly job; `llm(system, prompt) -> str` and `backtest(strategy, start, end, account)` are injectable."""
    if not await redis.set(LOCK, now.isoformat(), nx=True, ex=LOCK_TTL):
        return {"skipped": "running"}
    try:
        out = await _run(db, redis, now, llm or _default_llm, backtest)
    except Exception as exc:
        logger.exception("strategy builder failed")
        await jobs.mark(redis, jobs.BUILDER, ok=False, note=f"failed: {exc}")
        raise
    finally:
        await redis.delete(LOCK)  # ponytail: a run past the 6 h TTL may drop a newer run's lock
    return out


async def _run(db, redis, now, llm, backtest) -> dict:
    admin = await db["users"].find_one({"role": "admin"}, {"id": 1})
    admin_id = admin["id"] if admin else None
    out = {"drafted": 0, "passed": [], "rejected": [], "retired": await _retire_paused(db, admin_id, now)}
    from backend.risk.gate_backtest import backtest_account

    account = await backtest_account(db)  # size like the account that trades, as the gate does
    if not account.get("account_size", 0) > 0:
        logger.error("strategy builder: account size is %s; nothing tested", account.get("account_size"))
        await jobs.mark(redis, jobs.BUILDER, ok=False, note="account size is 0")
        return out
    lines = []
    # An injected `backtest` is the 5-minute one; swing always tests on the stored daily bars.
    notes = [await _run_horizon(db, redis, now, llm, backtest if horizon == "intraday" else None, horizon,
                                admin_id, out, lines) for horizon in HORIZONS]
    notes = [n for n in notes if n]

    text = f"🧪 Strategy builder: {out['drafted']} drafted, {len(out['passed'])} passed"
    text += (": " + "; ".join(lines) + ".") if lines else "."
    if out["retired"]:
        text += " Retired: " + ", ".join(f"built:{s}" for s in out["retired"]) + "."
    if notes:
        text += f" ({'; '.join(notes)})"
    await jobs.mark(redis, jobs.BUILDER, ok=True, note=text)
    if admin_id:
        await notify(db, admin_id, text)
    return out


async def _run_horizon(db, redis, now, llm, backtest, horizon, admin_id, out, lines) -> str:
    """Tests this horizon's waiting drafts, then asks the model for up to MAX_DRAFTS new ones;
    returns a note for the summary ("" when all went to plan)."""
    kwargs = {}
    if backtest is None and (history := await _history(db, redis, horizon)) is not None:
        backtest, kwargs = history
    holdout_days = (SWING_HOLDOUT if horizon == "swing" else HOLDOUT).days

    async def test(doc):
        try:
            status, verdict, fields = await _test(db, doc, backtest, kwargs, now)
        except Exception as exc:  # rejected, not left testing: a stuck draft would lock its owner out (R3)
            logger.exception("backtest of draft %s failed", doc["slug"])
            status, verdict, fields = "rejected", f"test failed: {type(exc).__name__}", {}
        if status == "active":
            if doc.get("owner_id") is None:  # a user's cap is enforced at submit
                out["retired"] += await _make_room(db, horizon)
            out["passed"].append(doc["slug"])
            year, hold = fields["metrics"]["year"], fields["metrics"]["holdout"]
            lines.append(f"built:{doc['slug']} (PF {year['pf']:.2f}, {year['trades']} trades, "
                         f"last {holdout_days} days {_rupees(hold['net'])})")
        else:
            out["rejected"].append((doc["slug"], verdict))
        await store.set_status(db, doc["slug"], status, verdict, **fields)

    waiting = [d for d in await store.all_drafts(db)
               if d["status"] == "testing" and store.horizon_of(d) == horizon][::-1]  # oldest first
    if backtest is not None:
        for doc in waiting:
            await test(doc)
    if backtest is None and horizon == "swing":  # stored bars missing is the ingest's fault: draft nothing
        return f"too few stored daily bars; {len(waiting)} swing draft(s) waiting"
    if backtest is None and waiting:
        return f"no 5-minute history source; {len(waiting)} draft(s) waiting"
    try:
        system, prompt = await _prompt(db, redis, admin_id, horizon)
        text = await llm(system, prompt)
        ideas = _parse(text)
        if not ideas:
            # A cut-off reply is replayed by the gateway's response cache for
            # the same prompt (seen 2026-10-07), so retry once with a new line.
            logger.warning("strategy builder: unusable reply (%d chars), retrying: %.200s", len(text or ""), text)
            ideas = _parse(await llm(system, f"{prompt}\n\n(attempt 2, {now.isoformat()})"))
    except Exception as exc:  # an LLM failure drafts nothing; nothing else changes
        logger.warning("strategy builder: no %s drafts: %s", horizon, exc)
        ideas = []
    stored = await store.all_drafts(db)
    # AI drafts only: a user's slug in a global "duplicate of" verdict would leak it.
    existing = [{"slug": d["slug"], "spec": d.get("spec")} for d in stored if d.get("owner_id") is None]
    taken = {d["slug"] for d in stored}
    for idea in ideas:
        raw = idea.get("spec")
        # The call decides the horizon, whatever the model wrote.
        spec, reason = validate_spec({**raw, "horizon": horizon} if isinstance(raw, dict) else raw, existing)
        # A refused spec is kept as text (model output may hold keys Mongo refuses, "$" or "."),
        # under a plain slug: only validated values are safe slug material.
        doc = {"slug": _unique(slugify(spec) if spec else "invalid", taken), "spec": spec or {},
               "thesis": str(idea.get("thesis") or "")[:300], "description": describe(spec) if spec else "",
               "drafted_at": now, "status": "testing" if spec else "rejected", "verdict": reason}
        if spec is None:
            doc["raw"] = json.dumps(raw, default=str)[:2000]
        await store.insert(db, doc)
        out["drafted"] += 1
        if spec is None:
            out["rejected"].append((doc["slug"], reason))
            continue
        existing.append({"slug": doc["slug"], "spec": spec})
        if backtest is not None:
            await test(doc)
    return "" if backtest is not None else "no 5-minute history source; drafts wait for next week"


async def test_one(db, redis, slug: str, now: datetime, backtest=None) -> dict:
    """Backtests one waiting draft (a user's, on submit) on its horizon's history. No LLM; its own lock,
    so it never waits on the weekly run. An injected `backtest` is the 5-minute one (no benchmark bars)."""
    key = f"builder:test:{slug}"
    if not await redis.set(key, now.isoformat(), nx=True, ex=3600):
        return {"slug": slug, "status": "testing", "verdict": "already running"}
    try:
        doc = await db[store.COLLECTION].find_one({"slug": slug, "status": "testing"})
        if doc is None:
            found = await db[store.COLLECTION].find_one({"slug": slug})
            return {"slug": slug, "status": found["status"] if found else "missing",
                    "verdict": found.get("verdict", "") if found else "no such draft"}
        kwargs = {}
        if backtest is None:
            history = await _history(db, redis, store.horizon_of(doc))
            if history is None:
                verdict = "waiting for market history"
                await store.set_status(db, slug, "testing", verdict)
                return {"slug": slug, "status": "testing", "verdict": verdict}
            backtest, kwargs = history
        try:
            status, verdict, fields = await _test(db, doc, backtest, kwargs, now)
        except Exception as exc:  # rejected so Re-test works; left testing it would lock its owner out (R3)
            logger.exception("backtest of draft %s failed", slug)
            status, verdict, fields = "rejected", f"test failed: {type(exc).__name__}", {}
        await store.set_status(db, slug, status, verdict, **fields)
        return {"slug": slug, "status": status, "verdict": verdict}
    finally:
        await redis.delete(key)


async def _spawn(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec("nice", "-n", "15", sys.executable, "-m", "backend.builder", *args)
    asyncio.create_task(proc.wait())  # reap it whenever it ends


async def spawn() -> None:
    await _spawn()


async def spawn_test(slug: str) -> None:
    await _spawn("--test", slug)


async def start_if_due(db, now: datetime) -> bool:
    """Starts this week's run on Friday (IST), once per ISO week; True if it started one now."""
    local = now.astimezone(IST)
    if local.weekday() != 4:
        return False
    week = local.strftime("%G-W%V")
    from pymongo.errors import DuplicateKeyError

    try:  # atomic with the unique index on week (store.ensure_indexes): two passes never both start one
        claimed = await db[store.RUNS].update_one(
            {"week": week}, {"$setOnInsert": {"week": week, "started_at": now}}, upsert=True)
    except DuplicateKeyError:  # a concurrent upsert claimed it first
        return False
    if claimed.upserted_id is None:
        return False
    await spawn()
    return True
