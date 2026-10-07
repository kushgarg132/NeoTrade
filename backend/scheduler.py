"""The daily post-close pass: scan for suggestions (whose theses also set
their news sentiment), refresh analyst verdicts, expire stale advice.

A single asyncio task rather than a scheduler dependency -- there are three
jobs, all on the same daily tick. The work itself lives in `run_daily_jobs`,
which takes `now` explicitly so it can be tested without waiting for 16:00.
"""

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from backend.ai.analyst_verdict import refresh_analyst_verdict
from backend.core.models import Fill, Side
from backend.engine.execution.options_costs import calculate_options_costs
from backend.engine.persistence import LedgerStore
from backend.engine.portfolio import Portfolio
from backend.engine.session import IST
from backend.instruments.master import InstrumentMaster
from backend.options.resolver import FO_UNDERLYINGS
from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
from backend.journal.sync import sync_user_trades
from backend.prefs import PrefsStore
from backend.suggestions.notify import notify, proposals_text
from backend.suggestions.scan import scan_universe
from backend.suggestions.store import SuggestionStore
from backend.suggestions.thesis import attach_theses

from backend.system.jobs import DAILY_PASS, mark

logger = logging.getLogger(__name__)

# 16:00 IST: half an hour after the 15:30 close, so the day's final daily
# candle is settled before the strategies read it.
RUN_HOUR = 16
RUN_MINUTE = 0

# Distributed lock so two workers running scheduler_loop concurrently
# produce exactly one daily pass, not two.
LOCK_KEY = "scheduler:daily_lock"
# IST date of the last finished daily pass. The long-term engine's 09:20
# check (backend/engine/autorun.py) re-runs the scan when this is stale,
# e.g. a deploy restarted the process across 16:00.
LAST_PASS_KEY = "scheduler:last_pass"
LOCK_TTL_MS = 2 * 60 * 60 * 1000  # 2 hours: covers a full pass, including
# per-user LLM calls, rather than a heartbeat/renewal loop -- a crashed
# holder self-heals at TTL expiry instead of leaving the pass permanently
# blocked.


def seconds_until_next_run(now: datetime) -> float:
    now_ist = now.astimezone(IST)
    target = now_ist.replace(hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0)
    if target <= now_ist:
        target += timedelta(days=1)
    return (target - now_ist).total_seconds()


async def run_daily_jobs(db, redis=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    prefs_store = PrefsStore(db)

    from backend.builder import store as builder_store
    await builder_store.refresh(db)  # the day's scans and plan replays build from the active specs
    expired = await SuggestionStore(db).expire_stale(now=now)
    options_closed = await close_expired_option_positions(db, redis=redis, now=now)
    verdicts_refreshed = await _refresh_analyst_verdicts(redis)

    scanned_users = 0
    created_total = 0
    for prefs in await prefs_store.scan_enabled_users():
        user_id = prefs["user_id"]
        try:
            created = await scan_universe(
                db, user_id=user_id, universe=prefs["universe"],
                account_size=prefs["account_size"], max_exposure=prefs["max_exposure"],
                source="scheduler", redis=redis, now=now,
            )
        except Exception as exc:
            # One user's bad universe must not cancel everyone else's scan.
            logger.exception("scheduled scan failed for %s: %s", user_id, exc)
            continue

        scanned_users += 1
        created_total += len(created)
        if created:
            await attach_theses(db, user_id, created)
            await notify(db, user_id, proposals_text(created, f"{len(created)} new long-term proposal(s) from today's close:"))

    journal_imported = await _sync_journals(db, redis)
    learning_changes = await _learn(db, now)
    # The day's game plans against no plan, on the same bars (backend/plan/replay.py).
    plan_replays = 0
    try:
        from backend.data.providers.yfinance_provider import YFinanceProvider
        from backend.plan.replay import replay_all

        plan_replays = await replay_all(db, YFinanceProvider(), now)
    except Exception as exc:
        logger.exception("plan replays failed: %s", exc)
    # Monthly, in its own process: re-tune strategy thresholds (backend/learning/retune.py).
    from backend.learning.retune import start_if_due
    try:
        await start_if_due(db, now)
    except Exception as exc:
        logger.warning("could not start the monthly re-tune: %s", exc)

    # Weekly portfolio review: Friday's pass, after the journal sync, while
    # that day's broker sessions are still valid.
    portfolios = 0
    if now.astimezone(IST).weekday() == 4:
        await _weekly_mirrors(db)
        from backend.portfolio.service import weekly_reviews
        try:
            portfolios = await weekly_reviews(db, redis)
        except Exception as exc:
            logger.exception("weekly portfolio reviews failed: %s", exc)

    logger.info(
        "daily pass: %d journal trade(s) imported, %d expired, %d option position(s) closed, %d verdict(s) refreshed, "
        "%d user(s) scanned, %d suggestion(s) created",
        journal_imported, expired, options_closed, verdicts_refreshed, scanned_users, created_total,
    )
    return {
        "expired": expired, "options_closed": options_closed,
        "verdicts_refreshed": verdicts_refreshed,
        "users": scanned_users, "created": created_total,
        "journal_imported": journal_imported, "portfolios_reviewed": portfolios,
        "learning_changes": learning_changes, "plan_replays": plan_replays,
    }


async def _sync_journals(db, redis) -> int:
    """Every broker only serves today's trade book, so a day nobody syncs is
    a day missing from the journal. 16:00 IST is after the close and before
    any broker's token expiry (Angel One midnight, Upstox 03:30, Kite 06:00)."""
    if redis is None:
        return 0  # broker sessions live in Redis; nothing is connected without it
    credentials = BrokerCredentialStore(db, fernet_from_settings())
    total = 0
    for user in await db["users"].find({}).to_list(length=None):
        try:
            total += (await sync_user_trades(db, redis, credentials, user["id"]))["imported"]
        except Exception as exc:
            logger.exception("journal sync failed for %s: %s", user["id"], exc)
    return total


async def _data_quality(db, redis) -> None:
    """Never fails the pass: the check reports, it does not gate."""
    from backend.system.data_quality import check
    from backend.system.jobs import DATA_QUALITY

    try:
        await mark(redis, DATA_QUALITY, True, json.dumps(await check(db)))
    except Exception as exc:
        logger.exception("data quality check failed: %s", exc)
        await mark(redis, DATA_QUALITY, False, f"{type(exc).__name__}: {exc}")


async def _run_locked(db, redis, pass_day: Optional[date] = None) -> Optional[dict]:
    """Acquires a Redis lock before running the daily pass. Returns None
    (pass skipped) if another worker already holds it. When `redis` is None
    the lock is skipped and the pass always runs -- matches every existing
    test's redis=None/mocked-redis calling convention for run_daily_jobs.

    `pass_day` is the IST day the pass counts for: today at 16:00, or the
    missed day when 09:20 catches up (backend/engine/autorun.py), so that
    day's own 16:00 pass still runs."""
    if redis is None:
        return await run_daily_jobs(db, redis=redis)

    token = str(uuid.uuid4())
    acquired = await redis.set(LOCK_KEY, token, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        logger.info("daily pass already running on another worker, skipping")
        return None

    try:
        # A worker that woke late can take the lock after the pass already
        # ran and released it: that day's pass is done, so skip.
        day = (pass_day or datetime.now(timezone.utc).astimezone(IST).date()).isoformat()
        last = await redis.get(LAST_PASS_KEY)
        last = last.decode() if isinstance(last, bytes) else last
        if last is not None and last >= day:
            logger.info("daily pass for %s already done, skipping", day)
            return None
        try:
            result = await run_daily_jobs(db, redis=redis)
        except Exception as exc:
            await mark(redis, DAILY_PASS, False, f"{type(exc).__name__}: {exc}")
            raise
        await redis.set(LAST_PASS_KEY, day)
        await mark(redis, DAILY_PASS, True, json.dumps(result, default=str))
        await _data_quality(db, redis)
        return result
    finally:
        # Only release if we still hold it -- never delete a lock some other
        # worker has since acquired after this one's TTL expired.
        current = await redis.get(LOCK_KEY)
        if current == token:
            await redis.delete(LOCK_KEY)


async def _default_spot_lookup(symbol: str) -> Optional[float]:
    # Local imports: keeps a hard `backend.database` dependency out of every
    # caller that injects its own spot_lookup (e.g. this module's tests).
    from backend.data.providers.yfinance_provider import YFinanceProvider
    from backend.database import db as _db

    instrument = await InstrumentMaster(_db.db).get("NSE", symbol)
    if instrument is None:
        return None
    quote = await YFinanceProvider().quote(instrument)
    price = quote.get("last_price")
    return float(price) if price else None


async def close_expired_option_positions(
    db,
    redis=None,
    now: Optional[datetime] = None,
    spot_lookup: Callable[[str], Awaitable[Optional[float]]] = _default_spot_lookup,
) -> int:
    """Closes every open option position (a Position whose symbol resolves
    to an NFO Instrument with expiry in the past) with a synthetic closing
    fill: worthless (premium 0) if the underlying's current mark leaves the
    put OTM, a simple intrinsic-value approximation if ITM -- not real
    physical/cash assignment mechanics, which are more involved than is
    worth modeling for a paper-only strategy. Returns the count closed."""
    now = now or datetime.now(timezone.utc)
    # Instrument.expiry round-trips through Mongo as a NAIVE UTC datetime
    # (see backend/instruments/loader.py's own note: Motor hands back naive
    # UTC datetimes regardless of what was stored) -- compare against a
    # naive `now` so this never raises on an aware-vs-naive comparison.
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    master = InstrumentMaster(db)
    prefs_store = PrefsStore(db)
    closed = 0

    for prefs in await prefs_store.scan_enabled_users():
        user_id = prefs["user_id"]
        ledger = LedgerStore(db, user_id=user_id)
        positions = await ledger.get_open_positions()

        for symbol, position in positions.items():
            contract = await master.get("NFO", symbol)
            if contract is None or contract.expiry is None:
                continue
            contract_expiry = (
                contract.expiry.replace(tzinfo=None) if contract.expiry.tzinfo is not None else contract.expiry
            )
            if contract_expiry >= now_naive:
                continue

            # The broker's NFO dump names each contract's underlying.
            spot = await spot_lookup(contract.name)
            if spot is None:
                continue

            intrinsic = max(contract.strike - spot, 0.0) if contract.instrument_type == "PE" else max(spot - contract.strike, 0.0)
            closing_side = Side.BUY if position.quantity < 0 else Side.SELL

            fill = Fill(
                order_id=str(uuid.uuid4()), symbol=symbol, side=closing_side,
                quantity=abs(position.quantity), price=intrinsic, timestamp=now,
                costs=calculate_options_costs(intrinsic, abs(position.quantity), closing_side),
            )
            portfolio = Portfolio()
            portfolio.positions = positions
            quantity_before = position.quantity
            portfolio.apply(fill)
            await ledger.on_fill(fill, quantity_before, portfolio.positions[symbol])
            await ledger.snapshot_positions(portfolio.positions)
            closed += 1

    return closed


async def _learn(db, now: datetime) -> int:
    """Each user with paper trades: judge them by setup and update the rules
    their next runs follow (backend/learning/adapt.py). Fridays, also send
    what it learned (backend/learning/report.py)."""
    from backend.learning.adapt import learn
    from backend.learning.report import weekly_text
    from backend.portfolio.service import _nifty
    from backend.suggestions.notify import notify

    users = await db["paper_trades"].distinct("user_id")
    nifty = await _nifty() if users else []
    total = 0
    for user_id in users:
        try:
            total += len(await learn(db, user_id, nifty, now))
            if now.astimezone(IST).weekday() == 4 and (text := await weekly_text(db, user_id, nifty, now)):
                await notify(db, user_id, text)
        except Exception as exc:
            logger.warning("learning pass failed for %s: %s", user_id, exc)
    return total


async def _weekly_mirrors(db) -> int:
    """Friday: each user with journal trades gets what charges took and how
    they compare with the Nifty (backend/journal/mirror.py)."""
    from backend.journal import mirror
    from backend.journal.roundtrips import build_round_trips
    from backend.journal.store import JournalStore
    from backend.portfolio.service import _nifty
    from backend.suggestions.notify import notify

    sent = 0
    nifty = await _nifty()
    for user_id in await db["journal_trades"].distinct("user_id"):
        try:
            trades = await JournalStore(db).list_trades(user_id)
            costs = mirror.costs(trades, build_round_trips(trades), (await PrefsStore(db).get(user_id))["account_size"])
            first = min(t["traded_at"] for t in trades)
            bench = mirror.benchmark(costs["net_pnl"], (await PrefsStore(db).get(user_id))["account_size"],
                                     first.date(), max(d for d, _ in nifty), nifty) if nifty else None
            text = mirror.text(costs, bench)
            prefs = await PrefsStore(db).get(user_id)
            roles = prefs.get("broker_roles") or {}
            if "ai" in roles.values() and "mine" in roles.values():
                from backend.journal.accounts import ai_vs_me
                month = ai_vs_me(trades, roles, {"ai": prefs["account_size"], "mine": prefs["account_size"]}, nifty)
                if month:
                    last = month[-1]
                    text += (f"\nThis month — AI account ₹{last['ai']['net_pnl']:+,.0f}, "
                             f"your account ₹{last['mine']['net_pnl']:+,.0f} (after charges).")
            sent += bool(await notify(db, user_id, text))
        except Exception as exc:
            logger.warning("weekly mirror failed for %s: %s", user_id, exc)
    return sent


async def _refresh_analyst_verdicts(redis) -> int:
    """Shared across every user's scan -- one refresh per curated symbol per day, not one
    per user. One symbol's failure must not cost every other symbol
    its refresh."""
    if redis is None:
        return 0
    count = 0
    for symbol in FO_UNDERLYINGS:
        try:
            await refresh_analyst_verdict(symbol, redis)
            count += 1
        except Exception as exc:
            logger.warning("analyst verdict refresh failed for %s: %s", symbol, exc)
    return count


async def scheduler_loop(db, redis=None) -> None:
    while True:
        await asyncio.sleep(seconds_until_next_run(datetime.now(timezone.utc)))
        try:
            await _run_locked(db, redis)
        except Exception as exc:
            # Never let one bad day kill the loop for every day after it.
            logger.exception("daily pass failed: %s", exc)


def start(db, redis=None) -> asyncio.Task:
    return asyncio.create_task(scheduler_loop(db, redis))
