"""The nightly scorecard: each user's intraday day replayed twice on the
same 5-minute bars through the same engine (run_backtest) -- A with the
day's plan versions applied at their times, B with no plan (what ran
before game plans existed). Stored in `plan_scorecards`, one doc per user
and day. Plan-chosen trades earn trust from a run of weeks where A beat B
(weeks_beating); nothing routes on it yet (Phase 15.4 shows it)."""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from backend.engine.session import IST
from backend.plan.gate import PlanGate, versions_source
from backend.plan.store import versions

logger = logging.getLogger(__name__)
SCORECARDS = "plan_scorecards"


def _side(result) -> dict:
    return {"net": result.total_pnl, "max_drawdown": result.max_drawdown, "trades": result.total_trades,
            "win_rate": result.win_rate}


async def replay_day(db, provider, user_id: str, day: date) -> Optional[dict]:
    from backend.datalayer.bars import prev_closes
    from backend.datalayer.catalysts import catalyst_map
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.engine.backtest import run_backtest
    from backend.instruments.master import InstrumentMaster
    from backend.learning.retune import current_params
    from backend.risk.gate_backtest import backtest_account
    from backend.strategies.registry import build_default_strategies

    start = datetime.combine(day, time(9, 15), IST)
    end = datetime.combine(day, time(15, 30), IST)
    run = await db["runs"].find_one({
        "user_id": user_id, "mode": "INTRADAY",
        "started_at": {"$gte": datetime.combine(day, time(0, 0), IST).astimezone(timezone.utc).replace(tzinfo=None),
                       "$lt": (datetime.combine(day, time(0, 0), IST) + timedelta(days=1)).astimezone(timezone.utc)
                       .replace(tzinfo=None)},
    }, sort=[("started_at", 1)])
    plans = await versions(db, user_id, day)
    if run is None or not plans:
        return None

    # B is the run as it was before plans: the base equity universe. A adds
    # the plan's news names. Neither trades the option feed's underlyings.
    params = run.get("params") or {}
    base = params.get("base_universe") or run.get("universe") or []
    adds = [s for s in params.get("plan_adds") or [] if s not in base]
    master = InstrumentMaster(db)
    resolved = {s: i for s in base + adds if (i := await master.get("NSE", s)) is not None}
    if not resolved:
        return None
    shared = {"catalysts": await catalyst_map(db, day, day), "sector_of": nifty200_sectors(),
              "prev_closes": {day.isoformat(): await prev_closes(db, list(resolved), day)},
              "params": await current_params(db)}
    account = await backtest_account(db)

    async def side(symbols: list[str], plan):
        instruments = [resolved[s] for s in symbols if s in resolved]
        universe = [i.tradingsymbol for i in instruments]
        symbol_for_token = {i.instrument_token: i.tradingsymbol for i in instruments}
        strategies = [s for s in build_default_strategies(universe=universe, symbol_for_token=symbol_for_token,
                                                          **shared) if s.spec.mode == "INTRADAY"]
        return await run_backtest(strategies, provider, instruments, start=start, end=end, timeframe="5m",
                                  plan=plan, **account)

    a = await side(base + adds, PlanGate(versions_source(plans)))
    if a.start_date == a.end_date:
        return None  # the provider had no bars for the day (run_backtest reports the requested start)
    b = await side(base, None)
    doc = {"user_id": user_id, "date": day.isoformat(), "a": _side(a), "b": _side(b),
           "plan_versions": len(plans), "at": datetime.now(timezone.utc)}
    await db[SCORECARDS].update_one({"user_id": user_id, "date": doc["date"]}, {"$set": doc}, upsert=True)
    return doc


async def replay_all(db, provider, now: datetime) -> int:
    day = now.astimezone(IST).date()
    count = 0
    for user_id in sorted(await db["runs"].distinct("user_id", {"mode": "INTRADAY"})):
        try:
            count += await replay_day(db, provider, user_id, day) is not None
        except Exception as exc:
            logger.exception("plan replay failed for %s: %s", user_id, exc)
    return count


async def weeks_beating(db, user_id: str) -> int:
    """Consecutive ISO weeks, newest first, where the plan (A) made more than
    no plan (B) with no deeper drawdown."""
    weeks: dict[tuple, list[dict]] = defaultdict(list)
    async for doc in db[SCORECARDS].find({"user_id": user_id}):
        weeks[date.fromisoformat(doc["date"]).isocalendar()[:2]].append(doc)
    streak = 0
    for key in sorted(weeks, reverse=True):
        docs = weeks[key]
        if (sum(d["a"]["net"] for d in docs) > sum(d["b"]["net"] for d in docs)
                and max(d["a"]["max_drawdown"] for d in docs) <= max(d["b"]["max_drawdown"] for d in docs)):
            streak += 1
        else:
            break
    return streak
