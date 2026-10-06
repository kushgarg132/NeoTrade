"""Daily paper runs, started without anyone pressing Start.

For every user with `auto_paper_intraday` on, one INTRADAY run is kept alive
from the 09:15 IST open to the 15:30 close on weekdays, then stopped (the
runner itself squares off MIS positions at 15:15). Checked once a minute on
every worker.

`auto_paper_longterm` is not a run. Long-term strategies read months of daily
bars, which a live feed cannot supply, so their ideas come from the
history-backed scan (backend/suggestions/scan.py, daily at 16:00 in
backend/scheduler.py). During the session this switch instead closes approved
long-term positions at their stop or target every 15 minutes
(backend/suggestions/exits.py), and from 09:20 rebalances the factor
portfolio on paper once a month (backend/factor/paper.py) and sends the
morning digest of proposals waiting for the user -- re-running the scan
first if the 16:00 pass was missed.

Which worker owns a user's run: a Redis key `autorun:{user_id}` holding that
worker's token, renewed every tick while its run is alive. Only a worker that
wins the key with SET NX starts a run, so two workers never both start one;
if the owner dies (a deploy), the key expires within KEY_TTL_MS and another
worker restarts the run. Mongo's run status is not used for this -- each
worker's startup marks every RUNNING row orphaned, including ones another
worker is still driving.

Not restarted the same day: a run the user stopped themselves during the
session, or once MAX_STARTS_PER_DAY auto runs have started (a crash loop).
"""

import asyncio
import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from backend.brokers.roles import RoleUnavailable, adapter_for

from backend.core.clock import SystemClock
from backend.engine.session import IST
from backend.prefs import PrefsStore
from backend.runs import ORPHANED, ACTIVE, RunStore
from backend.system.jobs import mark

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
KEY_TTL_MS = 150_000
MAX_STARTS_PER_DAY = 5
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
POLL_SECONDS = 60.0

# Which pref turns each mode's daily run on.
MODES = {"INTRADAY": "auto_paper_intraday"}
LONGTERM_PREF = "auto_paper_longterm"
EXIT_CHECK_MINUTES = 15
# The game plan (backend/plan/) is built between 08:45 and the open, so a
# fresh pre-open market read decides what the 09:15 run may trade.
PLAN_AT = time(8, 45)
PLAN_LOCK = "plan:build:{}:{}"
MORNING = time(9, 20)

# This process's identity for key ownership, and the auto runs it drives.
_TOKEN = str(uuid.uuid4())
_LOCAL: dict[str, str] = {}  # slot -> run_id


def in_session(now: datetime) -> bool:
    # ponytail: weekdays only, no NSE holiday calendar. On a holiday the feed
    # delivers no new bars, so the run idles and places nothing.
    local = now.astimezone(IST)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


def near_session(now: datetime, lead: timedelta = timedelta(minutes=45)) -> bool:
    """The session plus `lead` before the open: when background AI work is
    worth paying for, so scores and the brief are fresh at 09:15."""
    return in_session(now) or in_session(now + lead)


def _slot(user_id: str, mode: str) -> str:
    """One auto run per user per mode. INTRADAY keeps the bare user id it had
    before LONGTERM existed."""
    return user_id if mode == "INTRADAY" else f"{user_id}:{mode}"


def _split(slot: str) -> tuple[str, str]:
    user_id, _, mode = slot.partition(":")
    return user_id, mode or "INTRADAY"


def _key(slot: str) -> str:
    return f"autorun:{slot}"


async def _release(redis, slot: str) -> None:
    if await redis.get(_key(slot)) in (_TOKEN, _TOKEN.encode()):
        await redis.delete(_key(slot))


async def _stop_local(redis, runs: RunStore, slot: str) -> None:
    from backend.routers.trading import stop_background_run

    run_id = _LOCAL.pop(slot, None)
    if run_id is not None:
        await stop_background_run(run_id)
        await runs.mark_stopped(run_id)
    await _release(redis, slot)


async def _preopen_plans(db, redis, now: datetime, user_ids: list[str]) -> list[str]:
    """Builds today's plan once per auto-intraday user, across workers, once
    that user has a live feed."""
    from backend.plan import builder, store

    local = now.astimezone(IST)
    # Until the close: a broker login after the open still gets its plan before the run starts.
    if local.weekday() >= 5 or not (PLAN_AT <= local.time() < SESSION_CLOSE):
        return []
    built = []
    for user_id in user_ids:
        try:
            if await store.current(redis, user_id, local.date()) is not None:
                continue
            if not await live_feed_ready(user_id):
                continue  # no live feed, no auto run (_may_start): a plan would be an unused deep call
            if not await redis.set(PLAN_LOCK.format(user_id, local.date().isoformat()), _TOKEN, nx=True,
                                   px=3_600_000):
                continue  # another worker is building it
            await builder.build_plan(db, redis, user_id, now)
            built.append(user_id)
        except Exception as exc:
            logger.exception("game plan failed for %s: %s", user_id, exc)
    return built


# Brokers whose adapter streams ticks (build_feed in routers/trading.py uses them first).
STREAMING_BROKERS = ("kite", "upstox")


async def live_feed_ready(user_id: str) -> bool:
    """A logged-in broker that streams live ticks. Without one an intraday
    run would trade 15-minute-old yfinance candles, a record that says nothing
    about a live strategy -- so the auto run waits for the login instead."""
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.protocol import BrokerSessionState
    from backend.brokers.registry import get_broker_adapter
    from backend.database import db

    for broker in STREAMING_BROKERS:
        try:
            adapter = await get_broker_adapter(broker, user_id, get_credential_store(), db.redis)
            if await adapter.state() == BrokerSessionState.ACTIVE:
                return True
        except Exception as exc:
            logger.warning("live feed check for %s/%s failed: %s", user_id, broker, exc)
    return False


async def _may_start(runs: RunStore, user_id: str, mode: str, now: datetime, redis=None) -> bool:
    if mode == "INTRADAY" and not await live_feed_ready(user_id):
        return False  # waits for the broker login; checked again every tick
    if mode == "INTRADAY" and redis is not None:
        from backend.plan import store

        plan = await store.current(redis, user_id, now.astimezone(IST).date())
        if plan and plan.get("skip_day"):
            return False  # today's game plan sits the auto run out
    day_start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST).astimezone(timezone.utc)
    today = await runs.collection.find({
        "user_id": user_id, "mode": mode, "started_at": {"$gte": day_start},
    }).to_list(length=None)
    if any(r["status"] == ACTIVE and r["params"].get("origin") != "auto" for r in today):
        return False  # the user already started one by hand
    auto = [r for r in today if r["params"].get("origin") == "auto"]
    if any(r["status"] == "STOPPED" and r.get("error") is None for r in auto):
        return False  # the user stopped today's auto run themselves
    # The cap stops a crash loop; a run swept as orphaned by a restart (a
    # deploy) did not crash, so it does not count -- or a day of deploys
    # leaves open positions with no run to square them off.
    crashed_or_live = [r for r in auto if r.get("error") != ORPHANED]
    return len(crashed_or_live) < MAX_STARTS_PER_DAY


async def tick(db, redis, now: Optional[datetime] = None, launch=None) -> dict:
    """One pass. `launch` defaults to routers.trading.launch_run; tests pass
    a stub. Returns what it did, for logs and tests."""
    from backend.routers import trading

    now = now or SystemClock().now()
    launch = launch or trading.launch_run
    runs = RunStore(db)
    done = {"started": [], "renewed": [], "stopped": []}
    if redis is None:
        return done
    # A worker that died leaves its runs RUNNING until its alive key expires,
    # which can be after the startup sweep: sweep here too, or one dead run
    # blocks every new start for the day (one run per mode).
    await runs.close_orphaned(redis)

    enabled = {
        _slot(doc["user_id"], mode)
        for mode, pref in MODES.items()
        for doc in await db["user_prefs"].find({pref: True}).to_list(length=None)
    }

    try:
        await _autopilot_reminders(db, redis, now)
    except Exception as exc:
        logger.warning("autopilot reminders failed: %s", exc)

    planned = await _preopen_plans(db, redis, now, sorted(_split(slot)[0] for slot in enabled
                                                         if _split(slot)[1] == "INTRADAY"))
    if planned:
        done["planned"] = planned

    if not in_session(now):
        for slot in list(_LOCAL):
            await _stop_local(redis, runs, slot)
            done["stopped"].append(slot)
        return done

    for slot in list(_LOCAL):
        if slot not in enabled:  # turned off mid-session
            await _stop_local(redis, runs, slot)
            done["stopped"].append(slot)

    prefs_store = PrefsStore(db)
    for user_id in sorted(
        doc["user_id"] for doc in await db["user_prefs"].find({LONGTERM_PREF: True}).to_list(length=None)
    ):
        try:
            if await _longterm_pass(db, redis, user_id, now):
                done.setdefault("longterm", []).append(user_id)
        except Exception as exc:
            logger.exception("long-term pass failed for %s: %s", user_id, exc)

    for slot in sorted(enabled):
        user_id, mode = _split(slot)
        run_id = _LOCAL.get(slot)
        if run_id is not None and run_id in trading._RUNS:
            await redis.set(_key(slot), _TOKEN, xx=True, px=KEY_TTL_MS)
            done["renewed"].append(slot)
            continue
        _LOCAL.pop(slot, None)  # our run ended (stopped by the user, or crashed)
        await _release(redis, slot)

        if not await _may_start(runs, user_id, mode, now, redis=redis):
            continue
        if not await redis.set(_key(slot), _TOKEN, nx=True, px=KEY_TTL_MS):
            continue  # another worker owns this run
        try:
            prefs = await prefs_store.get(user_id)
            _LOCAL[slot] = await launch(
                user_id, mode, prefs["universe"], POLL_SECONDS, runs, origin="auto",
            )
            done["started"].append(slot)
        except Exception as exc:
            logger.exception("auto-run start failed for %s: %s", slot, exc)
            await _release(redis, slot)
    return done


def _previous_weekday(day):
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


async def _longterm_pass(db, redis, user_id: str, now: datetime) -> bool:
    """Exit checks once per EXIT_CHECK_MINUTES bucket, and once a day from
    MORNING the catch-up scan + digest. Redis SET NX makes each happen on
    one worker only. Returns whether this worker did anything."""
    from backend.scheduler import LAST_PASS_KEY
    from backend.suggestions.exits import check_exits
    from backend.suggestions.notify import exits_text, notify, proposals_text
    from backend.suggestions.scan import scan_universe
    from backend.suggestions.store import SuggestionStore

    local = now.astimezone(IST)
    day = local.date().isoformat()
    did = False

    bucket = (local.hour * 60 + local.minute) // EXIT_CHECK_MINUTES
    if await redis.set(f"longterm:{user_id}:{day}:{bucket}", _TOKEN, nx=True, px=EXIT_CHECK_MINUTES * 60_000 * 2):
        did = True
        closed = await check_exits(db, user_id, now=now)
        if closed:
            await notify(db, user_id, exits_text(closed))
        if (await PrefsStore(db).get(user_id)).get("autopilot_enabled"):
            from backend.autopilot.service import check_exits as autopilot_exits
            await autopilot_exits(db, redis, user_id, now=now)

    if local.time() >= MORNING and await redis.set(f"longterm:{user_id}:{day}:morning", _TOKEN, nx=True, px=86_400_000):
        did = True
        last_pass = await redis.get(LAST_PASS_KEY)
        last_pass = last_pass.decode() if isinstance(last_pass, bytes) else last_pass
        if last_pass is None or last_pass < _previous_weekday(local.date()).isoformat():
            prefs = await PrefsStore(db).get(user_id)
            logger.info("16:00 scan missed (last pass %s); catching up for %s", last_pass, user_id)
            await scan_universe(
                db, user_id=user_id, universe=prefs["universe"], account_size=prefs["account_size"],
                max_exposure=prefs["max_exposure"], source="scheduler", redis=redis, now=now,
            )
        # The factor portfolio is the automatic long-term strategy: rebalanced
        # on paper at the first morning pass of each month (backend/factor/).
        from backend.factor import paper as factor_paper
        if await factor_paper.due(db, user_id, now):
            try:
                summary = await factor_paper.rebalance(db, user_id, now=now)
                await notify(db, user_id, factor_paper.summary_text(summary))
            except Exception as exc:
                logger.exception("factor rebalance failed for %s: %s", user_id, exc)
        # Per-symbol proposals have no backtest evidence: they wait for the
        # user -- unless the user turned the autopilot on for its AI account.
        store = SuggestionStore(db)
        await store.expire_stale(now=now)
        pending = await store.list(user_id, mode="LONGTERM", status="PENDING", limit=100)
        if (await PrefsStore(db).get(user_id)).get("autopilot_enabled"):
            pending = await _autopilot_proposals(db, redis, store, user_id, pending, now)
        if pending:
            pending.sort(key=lambda s: s["expires_at"])
            await notify(db, user_id, proposals_text(pending, f"Good morning: {len(pending)} long-term proposal(s) waiting."))
    return did


async def _autopilot_proposals(db, redis, store, user_id: str, pending: list[dict], now: datetime,
                               source: str = "engine", heading: str = "morning pass") -> list[dict]:
    """Hands pending stock proposals to the autopilot (backend/autopilot/),
    best score first, resized to the per-trade cap in force, with one
    summary note; returns the ones it did not take."""
    from backend.autopilot import fence, service
    from backend.core.models import Side
    from backend.suggestions.notify import notify

    regime = (await service.regime_now(redis)).get("label")
    cap = fence.trade_cap(await PrefsStore(db).get(user_id), regime)
    left, bought, refused = [], [], []
    for s in sorted(pending, key=lambda s: (s.get("score") or {}).get("final") or 0.0, reverse=True):
        entry = s.get("entry_ref") or 0
        quantity = min(int(s["quantity"]), int(cap // entry)) if entry > 0 else 0
        if s.get("option_contract") or quantity < 1:
            left.append(s)
            continue
        result = await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=s["symbol"], side=Side(s["side"]), quantity=quantity, product="CNC",
            source=source, reason=f"{'News' if source == 'news' else 'Engine'} proposal ({s.get('strategy') or 'scan'}): {', '.join(s.get('reason_codes') or [])}"),
            now=now, suggestion_id=s["id"], quiet=True)
        if result["status"] in ("FILLED", "SENT"):
            await store.decide(user_id, s["id"], status="EXECUTED", reason="autopilot", now=now)
            bought.append(f"{s['symbol']} ×{quantity}")
        else:
            refused.append(f"{s['symbol']} ({result.get('reason')})")
            left.append(s)
    if bought or refused:
        lines = [f"🤖 Autopilot, {heading} on the AI account:"]
        if bought:
            lines.append("Bought: " + ", ".join(bought))
        if refused:
            lines.append("Refused: " + "; ".join(refused[:5]) + (" …" if len(refused) > 5 else ""))
        await notify(db, user_id, "\n".join(lines))
    return left


async def _autopilot_reminders(db, redis, now: datetime) -> None:
    """09:00-09:15 IST on weekdays: remind once if the autopilot is on but
    the AI account is not logged in -- otherwise it cannot trade that day."""
    from backend.auth.broker_credentials import get_credential_store
    from backend.suggestions.notify import notify

    local = now.astimezone(IST)
    if local.weekday() >= 5 or not (time(9, 0) <= local.time() < SESSION_OPEN):
        return
    for doc in await db["user_prefs"].find({"autopilot_enabled": True}).to_list(length=None):
        user_id = doc["user_id"]
        if not await redis.set(f"autopilot:remind:{user_id}:{local.date()}", _TOKEN, nx=True, px=86_400_000):
            continue
        try:
            await adapter_for(user_id, "ai", get_credential_store(), redis)
        except RoleUnavailable as exc:
            await notify(db, user_id, f"🤖 {exc.reason} Log in before 09:15 or the autopilot can't trade today.")


async def autorun_loop(db, redis) -> None:
    while True:
        try:
            result = await tick(db, redis)
            if result["started"] or result["stopped"]:
                logger.info("auto-run: %s", result)
            await mark(redis, "autorun", True, f"started {len(result['started'])}, stopped {len(result['stopped'])}")
        except Exception as exc:
            logger.exception("auto-run tick failed: %s", exc)
            await mark(redis, "autorun", False, f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(autorun_loop(db, redis))
