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
(backend/suggestions/exits.py), and from 09:20 buys every pending long-term
stock proposal on paper at its live mark and sends the morning digest --
re-running the scan first if the 16:00 pass was missed.

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

from backend.core.clock import SystemClock
from backend.engine.session import IST
from backend.prefs import PrefsStore
from backend.runs import ACTIVE, RunStore

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
MORNING = time(9, 20)
MIN_FILL_FRACTION = 0.25  # an auto-approval cut below this share of its size is skipped

# This process's identity for key ownership, and the auto runs it drives.
_TOKEN = str(uuid.uuid4())
_LOCAL: dict[str, str] = {}  # slot -> run_id


def in_session(now: datetime) -> bool:
    # ponytail: weekdays only, no NSE holiday calendar. On a holiday the feed
    # delivers no new bars, so the run idles and places nothing.
    local = now.astimezone(IST)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


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


async def _may_start(runs: RunStore, user_id: str, mode: str, now: datetime) -> bool:
    day_start = datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST).astimezone(timezone.utc)
    today = await runs.collection.find({
        "user_id": user_id, "mode": mode, "started_at": {"$gte": day_start},
    }).to_list(length=None)
    if any(r["status"] == ACTIVE and r["params"].get("origin") != "auto" for r in today):
        return False  # the user already started one by hand
    auto = [r for r in today if r["params"].get("origin") == "auto"]
    if any(r["status"] == "STOPPED" and r.get("error") is None for r in auto):
        return False  # the user stopped today's auto run themselves
    return len(auto) < MAX_STARTS_PER_DAY


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

    enabled = {
        _slot(doc["user_id"], mode)
        for mode, pref in MODES.items()
        for doc in await db["user_prefs"].find({pref: True}).to_list(length=None)
    }

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

        if not await _may_start(runs, user_id, mode, now):
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
        store = SuggestionStore(db)
        await store.expire_stale(now=now)
        pending = await store.list(user_id, mode="LONGTERM", status="PENDING", limit=100)
        approved = await _auto_approve(db, store, user_id, pending, now)
        if approved:
            await notify(db, user_id, proposals_text(approved, f"Good morning: bought {len(approved)} long-term proposal(s) on paper."))
        pending = [s for s in pending if s not in approved]
        if pending:
            pending.sort(key=lambda s: s["expires_at"])
            await notify(db, user_id, proposals_text(pending, f"Good morning: {len(pending)} long-term proposal(s) waiting."))
    return did


async def _auto_approve(db, store, user_id: str, pending: list[dict], now: datetime) -> list[dict]:
    """Approves pending long-term stock proposals on paper at their live
    mark, as the Approve button does -- best score first, and only while
    they fit: each is cut to `per_trade_cap`, and the total (open paper
    positions included) stays within min(account_size, max_exposure).
    Options, symbols without a mark, and whatever no longer fits are left
    pending for the user."""
    from backend.engine.persistence import LedgerStore
    from backend.marks import mark_prices
    from backend.suggestions.service import execute_suggestion
    from backend.ws.publish import publisher_for

    stocks = [s for s in pending if not s.get("option_contract")]
    if not stocks:
        return []
    stocks.sort(key=lambda s: (s.get("score") or {}).get("final") or 0.0, reverse=True)
    marks = await mark_prices(db, {s["symbol"] for s in stocks})
    ledger = LedgerStore(db, user_id=user_id, on_change=publisher_for(user_id))
    prefs = await PrefsStore(db).get(user_id)
    held = sum(abs(p.quantity) * p.avg_price for p in (await ledger.get_open_positions(venue="paper")).values())
    room = min(prefs["account_size"], prefs["max_exposure"]) - held
    approved = []
    for suggestion in stocks:
        price = marks.get(suggestion["symbol"])
        if not price:
            continue
        intended = int(min(suggestion["quantity"], prefs["per_trade_cap"] // price))
        quantity = int(min(intended, room // price))
        # Whatever room is left must buy a real position, not a share or two of dust.
        if quantity < 1 or quantity < MIN_FILL_FRACTION * intended:
            continue
        try:
            order = await execute_suggestion({**suggestion, "quantity": quantity}, ledger, price, now=now)
        except Exception as exc:
            logger.exception("auto-approve of %s failed: %s", suggestion["id"], exc)
            continue
        if await store.decide(user_id, suggestion["id"], status="EXECUTED", reason="auto-approved", order_id=order.id, now=now) is None:
            logger.warning("suggestion %s was decided concurrently after order %s", suggestion["id"], order.id)
        room -= quantity * price
        approved.append(suggestion)
    return approved


async def autorun_loop(db, redis) -> None:
    while True:
        try:
            result = await tick(db, redis)
            if result["started"] or result["stopped"]:
                logger.info("auto-run: %s", result)
        except Exception as exc:
            logger.exception("auto-run tick failed: %s", exc)
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(autorun_loop(db, redis))
