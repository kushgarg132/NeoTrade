"""Monthly re-tune of each strategy's thresholds (its PARAMS, varied over
its GRID -- backend/strategies/base.py).

Per strategy, over the last WINDOW_DAYS: every variant is backtested on
the first part of the window, and the best by net Sharpe (with at least
MIN_TRAIN_TRADES trades) is chosen. It replaces the current params only if,
on the later part it never saw, it makes money, beats the current params,
and its deflated Sharpe (backend/factor/validate.py) clears MIN_DSR counting
every variant ever tried for that strategy. Every attempt is recorded in
`strategy_retunes`; the latest accepted one per strategy is what runs.

Daily-bar strategies are re-tuned on three years of yfinance closes;
5-minute ones on a year from the admin's Upstox (or Kite) session
(backend/risk/gate_backtest.py::intraday_history), and skipped when neither
is logged in -- yfinance's ~60 days of 5-minute bars is too short a test.

CPU-heavy (dozens of multi-year backtests), so the daily pass starts it as
its own low-priority process (`python -m backend.learning.retune`), never
inside the API worker.
"""

import asyncio
import itertools
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.factor.validate import deflated_sharpe

logger = logging.getLogger(__name__)

WINDOW_DAYS = {"1d": 3 * 365, "5m": 365}
TRAIN_SHARE = 2 / 3
# Calendar days of history before the test part, so 200-day averages and
# indicator warmups are ready when it starts. Trades before it don't count.
WARMUP_DAYS = {"1d": 300, "5m": 7}
MIN_TRAIN_TRADES = 20
MIN_DSR = 0.95
ACCOUNT = 1_000_000.0  # run_backtest's default account_size


def variants(grid: dict[str, list]) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]


def _daily(trades: list[dict], start: datetime, end: datetime) -> pd.Series:
    """Net P&L per weekday as a fraction of the account, zero on days
    without a trade, over [start, end)."""
    days = pd.bdate_range(start.date(), end.date() - timedelta(days=1))
    pnl = pd.Series(0.0, index=days)
    for t in trades:
        day = pd.Timestamp(datetime.fromisoformat(t["timestamp"]).date())
        if day in pnl.index:
            pnl[day] += t["net_pnl"]
    return pnl / ACCOUNT


def _sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std()) if len(r) > 1 and r.std() > 0 else 0.0


def _summary(r: pd.Series, trades: list[dict]) -> dict:
    return {"trades": len(trades), "net": round(sum(t["net_pnl"] for t in trades), 2), "sharpe": round(_sharpe(r), 4)}


def _at(trade: dict) -> datetime:
    at = datetime.fromisoformat(trade["timestamp"])
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


async def retune_strategy(strategy, backtest, current: dict, start: datetime, split: datetime,
                          end: datetime, past_trials: list[float], candidates: list[dict] | None = None) -> dict:
    """`strategy` gives spec.name, spec.timeframe and GRID;
    `backtest(params, start, end)` returns a BacktestResult. `candidates`
    replaces the grid (a queued hypothesis, backend/learning/hypotheses.py).
    Returns the record to store; `accepted` says whether `params` should run."""
    doc = {"strategy": strategy.spec.name, "current": current, "accepted": False}

    train = []
    for params in candidates if candidates is not None else variants(strategy.GRID):
        result = await backtest(params, start, split)
        returns = _daily(result.trades, start, split)
        train.append((params, returns, result.trades))
    trial_sharpes = past_trials + [_sharpe(r) for _, r, _ in train]
    doc.update(trials=len(trial_sharpes), trial_sharpes=[_sharpe(r) for _, r, _ in train],
               train={str(p): _summary(r, t) for p, r, t in train})

    eligible = [(p, r) for p, r, t in train if len(t) >= MIN_TRAIN_TRADES]
    if not eligible:
        return {**doc, "params": current, "reason": f"no variant had {MIN_TRAIN_TRADES}+ trades in sample"}
    best, _ = max(eligible, key=lambda pr: _sharpe(pr[1]))
    doc["params"] = best
    if best == current:
        return {**doc, "reason": "current params are still best in sample"}

    warm = split - timedelta(days=WARMUP_DAYS.get(strategy.spec.timeframe, 0))
    out = {}
    for label, params in (("best", best), ("current", current)):
        result = await backtest(params, warm, end)
        trades = [t for t in result.trades if _at(t) >= split]
        out[label] = (_daily(trades, split, end), trades)
    doc["test"] = {label: _summary(r, t) for label, (r, t) in out.items()}
    best_net, current_net = doc["test"]["best"]["net"], doc["test"]["current"]["net"]
    if best_net <= max(current_net, 0.0):
        return {**doc, "reason": f"out of sample it made ₹{best_net:,.0f} against ₹{current_net:,.0f} for the current params"}
    doc["dsr"] = deflated_sharpe(out["best"][0], trial_sharpes)
    if doc["dsr"] < MIN_DSR:
        return {**doc, "reason": f"deflated Sharpe {doc['dsr']:.2f} < {MIN_DSR} over {len(trial_sharpes)} variants tried"}
    return {**doc, "accepted": True, "reason": "won out of sample and passed the deflated Sharpe"}


async def current_params(db) -> dict[str, dict]:
    """Each strategy's latest accepted params; strategies never re-tuned
    are absent and keep their defaults."""
    latest = {}
    async for doc in db["strategy_retunes"].find({"accepted": True}).sort("at", 1):
        latest[doc["strategy"]] = doc["params"]
    return latest


class _Memo:
    """One history fetch per symbol, however many variants replay it."""

    def __init__(self, provider) -> None:
        self._provider, self._cache = provider, {}

    async def history(self, instrument, interval, period):
        key = (instrument.tradingsymbol, interval, period)
        if key not in self._cache:
            self._cache[key] = await self._provider.history(instrument, interval, period)
        return self._cache[key]

    async def quote(self, instrument):
        return await self._provider.quote(instrument)


# Inputs some strategies get at construction (news catalysts, previous
# closes, sector map); a re-tune variant must keep them or it tunes a
# strategy that never fires, or a different one.
INJECTED = ("catalysts", "prev_closes", "sector_of")


def variant(strategy, universe: list[str], symbol_for_token: dict[int, str], params: dict):
    """`strategy` rebuilt with `params`, keeping its injected inputs."""
    kept = {k: getattr(strategy, k) for k in INJECTED if hasattr(strategy, k)}
    return type(strategy)(universe, symbol_for_token, params, **kept)


async def run_all(db, provider, now: datetime, intraday=None) -> list[dict]:
    """`provider` serves daily bars; `intraday` (or None, skipping them) 5-minute ones."""
    from backend.components.quant.indian_stocks import ALL_SCAN_STOCKS
    from backend.engine.backtest import run_backtest
    from backend.instruments.master import InstrumentMaster
    from backend.learning.hypotheses import test_queued
    from backend.strategies.registry import build_default_strategies

    master = InstrumentMaster(db)
    instruments = [i for s in ALL_SCAN_STOCKS if (i := await master.get("NSE", s)) is not None]
    universe = [i.tradingsymbol for i in instruments]
    symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments}
    memos = {"1d": _Memo(provider), "5m": _Memo(intraday) if intraday is not None else None}
    accepted = await current_params(db)
    from backend.risk.gate_backtest import backtest_account
    account = await backtest_account(db)  # size like the account that trades
    docs = []
    from backend.datalayer.catalysts import catalyst_map
    from backend.datalayer.news_sources import nifty200_sectors

    catalysts = await catalyst_map(db, (now - timedelta(days=max(WINDOW_DAYS.values()))).date(), now.date())
    for strategy in build_default_strategies(universe=universe, symbol_for_token=symbol_for_token, params=accepted,
                                             catalysts=catalysts, sector_of=nifty200_sectors()):
        timeframe = strategy.spec.timeframe
        if not getattr(strategy, "GRID", None) or timeframe not in WINDOW_DAYS or memos.get(timeframe) is None:
            continue
        memo = memos[timeframe]
        name = strategy.spec.name

        async def backtest(params, start, end, strategy=strategy, timeframe=timeframe, memo=memo):
            return await run_backtest([variant(strategy, universe, symbol_for_token, params)], memo, instruments,
                                      start=start, end=end, timeframe=timeframe, **account)

        start = now - timedelta(days=WINDOW_DAYS[timeframe])
        split = start + (now - start) * TRAIN_SHARE
        past = [s for d in await db["strategy_retunes"].find({"strategy": name}).to_list(None)
                for s in d.get("trial_sharpes", [])]
        try:
            doc = await retune_strategy(strategy, backtest, strategy.p, start, split, now, past)
        except Exception as exc:
            logger.exception("re-tune of %s failed", name)
            doc = {"strategy": name, "accepted": False, "reason": f"failed: {exc}"}
        doc["at"] = now
        await db["strategy_retunes"].insert_one(dict(doc))
        logger.info("re-tune %s: %s (%s)", name, "accepted" if doc["accepted"] else "kept", doc["reason"])
        docs.append(doc)

        # Then the LLM's queued ideas for it, against whatever runs now.
        running = doc["params"] if doc["accepted"] else strategy.p
        past += doc.get("trial_sharpes", [])
        docs += await test_queued(db, strategy, backtest, running, start, split, now, past, now)
    return docs


async def spawn() -> None:
    proc = await asyncio.create_subprocess_exec("nice", "-n", "15", sys.executable, "-m", "backend.learning.retune")
    asyncio.create_task(proc.wait())  # reap it whenever it ends


async def start_if_due(db, now: datetime) -> bool:
    """Starts this month's re-tune once; True if it started one now."""
    month = now.strftime("%Y-%m")
    if await db["retune_runs"].find_one({"month": month}):
        return False
    await db["retune_runs"].insert_one({"month": month, "started_at": now})
    await spawn()
    return True


async def _main() -> None:
    from backend.data.providers.yfinance_provider import YFinanceProvider
    from backend.database import db

    from backend.learning.hypotheses import propose
    from backend.strategies.registry import build_default_strategies

    await db.connect_to_database()
    from backend.risk.gate_backtest import intraday_history

    now = datetime.now(timezone.utc)
    source, intraday = await intraday_history(db.db, db.redis)
    print("intraday history:", source or "none (5-minute strategies skipped)", flush=True)
    strategies = {s.spec.name: s for s in build_default_strategies(params=await current_params(db.db))}
    for h in await propose(db.db, strategies, now):
        print("hypothesis queued:", h["strategy"], h["params"], "-", h["rationale"], flush=True)
    for doc in await run_all(db.db, YFinanceProvider(), now, intraday=intraday):
        print(doc["strategy"], "accepted" if doc["accepted"] else "kept", "-", doc["reason"], flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
