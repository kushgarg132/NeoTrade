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


from backend.core.market_calendar import is_trading_day, previous_trading_day
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
LOGIN_REMIND, LOGIN_REMIND_AGAIN = time(8, 30), time(9, 5)
POLL_SECONDS = 60.0

# Which pref turns each mode's daily run on.
MODES = {"INTRADAY": "auto_paper_intraday"}
LONGTERM_PREF = "auto_paper_longterm"
EXIT_CHECK_MINUTES = 15
MORNING = time(9, 20)

# This process's identity for key ownership, and the auto runs it drives.
_TOKEN = str(uuid.uuid4())
_LOCAL: dict[str, str] = {}  # slot -> run_id


def in_session(now: datetime) -> bool:
    local = now.astimezone(IST)
    return is_trading_day(local.date()) and SESSION_OPEN <= local.time() < SESSION_CLOSE


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
    from backend import app_settings
    if enabled and not await app_settings.lab_on("the intraday auto-run", db):
        enabled = set()  # running slots stop below, as if turned off mid-session
        done["idle"] = "lab off"

    try:
        await _login_reminders(db, redis, now)
    except Exception as exc:
        logger.warning("login reminders failed: %s", exc)
    try:
        from backend.portfolio.digest import send_premarket
        await send_premarket(db, redis, now)
    except Exception as exc:
        logger.warning("pre-market digest failed: %s", exc)
    try:
        from backend.reports.weekly import send as send_weekly
        await send_weekly(db, redis, now)
    except Exception as exc:
        logger.warning("weekly report failed: %s", exc)

    try:
        from backend.summaries import holding
        await holding.run_all(db, redis, now)  # a note under each bad-news / results-soon action
    except Exception as exc:
        logger.warning("holding notes failed: %s", exc)

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
    # The autopilot acts in this pass (09:20 proposals, its exits), so it
    # keeps the pass running even with the long-term switch off -- and with
    # both off while it still holds something, so its exits still run.
    users = {doc["user_id"] for doc in await db["user_prefs"].find(
        {"$or": [{LONGTERM_PREF: True}, {"autopilot_enabled": True}]}).to_list(length=None)}
    # Likewise anyone with app-placed positions on their own account: their exit alerts.
    users |= {u.split(":")[0] for u in await db["paper_trades"].distinct(
        "user_id", {"status": "OPEN", "$or": [{"via": {"$regex": "^autopilot:"}}, {"user_id": {"$regex": ":mine$"}}]})}
    for user_id in sorted(users):
        try:
            if await _longterm_pass(db, redis, user_id, now):
                done.setdefault("longterm", []).append(user_id)
        except Exception as exc:
            logger.exception("long-term pass failed for %s: %s", user_id, exc)

    # The owner's own stop / target on a holding: a step of its own, not the
    # long-term pass (that would start a factor book and morning ideas).
    for user_id in sorted(await db["holding_theses"].distinct(
            "user_id", {"$or": [{"stop": {"$gt": 0}}, {"target": {"$gt": 0}}]})):
        try:
            await _level_pass(db, redis, user_id, now)
        except Exception as exc:
            logger.warning("level alerts failed for %s: %s", user_id, exc)

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
            done.setdefault("idle", "no live feed or already run today")
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


async def _level_pass(db, redis, user_id: str, now: datetime) -> None:
    """Stop / target hits on the owner's holdings, once per EXIT_CHECK_MINUTES
    bucket on one worker; Telegram once per level (`actions.level_alerts`)."""
    from backend import alerts
    from backend.mine import actions

    local = now.astimezone(IST)
    bucket = (local.hour * 60 + local.minute) // EXIT_CHECK_MINUTES
    if await redis.set(f"levels:{user_id}:{local.date().isoformat()}:{bucket}", _TOKEN, nx=True,
                       px=EXIT_CHECK_MINUTES * 60_000 * 2):
        for a in await actions.level_alerts(db, redis, user_id, now):
            s = a["symbol"]
            title = f"{'Sell' if a['kind'] == 'stop_hit' else 'Target'} · {s}"
            if not await alerts.alert(db, user_id, "exit", title, [a["detail"]], symbol=s, buttons=alerts.sell_buttons(
                    s, a["action"]["quantity"], f"/mine/stock/{s}")):
                await redis.delete(f"mine:alert:{user_id}:{a['id']}")  # unsent: free the once-per-level key so the next pass retries


async def _longterm_pass(db, redis, user_id: str, now: datetime) -> bool:
    """Exit checks once per EXIT_CHECK_MINUTES bucket, and once a day from
    MORNING the catch-up scan + digest. Redis SET NX makes each happen on
    one worker only. Returns whether this worker did anything."""
    from backend import scheduler
    from backend.scheduler import LAST_PASS_KEY
    from backend.suggestions.exits import check_exits
    from backend import alerts
    from backend.suggestions.notify import exit_line, proposals_text
    from backend.suggestions.store import SuggestionStore

    local = now.astimezone(IST)
    day = local.date().isoformat()
    did = False

    bucket = (local.hour * 60 + local.minute) // EXIT_CHECK_MINUTES
    if await redis.set(f"longterm:{user_id}:{day}:{bucket}", _TOKEN, nx=True, px=EXIT_CHECK_MINUTES * 60_000 * 2):
        did = True
        closed = await check_exits(db, user_id, now=now)
        for c in closed:
            await alerts.alert(db, user_id, "exit", f"Sell · {c['symbol']}", [exit_line(c)], symbol=c["symbol"],
                               buttons=alerts.sell_buttons(c["symbol"], int(c["quantity"]), f"/mine/stock/{c['symbol']}"))
        # Off or on, the autopilot's open positions keep their exits.
        from backend.autopilot.service import check_exits as autopilot_exits
        await autopilot_exits(db, redis, user_id, now=now)
        from backend.autopilot import picks as picks_trading
        try:  # Picks: out at their stop or target, else the close of their horizon (backend/autopilot/picks.py)
            await picks_trading.exit_due(db, redis, user_id, now)
        except Exception as exc:
            logger.exception("picks exits failed for %s: %s", user_id, exc)
        if local.time() >= MORNING:  # the rotation book trades toward this week's target; retries refused buys
            await _rotation(db, redis, user_id, now, morning=False)

    if local.time() >= MORNING and await redis.set(f"longterm:{user_id}:{day}:morning", _TOKEN, nx=True, px=86_400_000):
        did = True
        last_pass = await redis.get(LAST_PASS_KEY)
        last_pass = last_pass.decode() if isinstance(last_pass, bytes) else last_pass
        missed = previous_trading_day(local.date())
        if last_pass is None or last_pass < missed.isoformat():
            # The whole pass, not just the scan: learning, plan replays, the
            # re-tune and the data check are lost too when a deploy kills 16:00.
            # Under the daily lock, so other users' morning passes skip it. In
            # the background: inline it held this tick ~7 minutes, the auto-run
            # key lapsed and the other worker started a second intraday run.
            logger.info("16:00 pass missed (last pass %s); catching up for %s", last_pass, missed)
            asyncio.create_task(_catch_up(db, redis, missed))
        # The factor portfolio is the automatic long-term strategy: rebalanced
        # on paper at the first morning pass of each month (backend/factor/).
        from backend.factor import paper as factor_paper
        if await factor_paper.due(db, user_id, now):
            try:
                summary = await factor_paper.rebalance(db, user_id, now=now)
                await alerts.alert(db, user_id, "learning", "Factor portfolio rebalanced (paper)",
                                   factor_paper.summary_text(summary).splitlines())
            except Exception as exc:
                logger.exception("factor rebalance failed for %s: %s", user_id, exc)
        # The AI account's only entries: the weekly rotation (backend/autopilot/rotation.py).
        await _rotation(db, redis, user_id, now, morning=True)
        # Per-symbol proposals have no backtest evidence: they wait for the user.
        store = SuggestionStore(db)
        await store.expire_stale(now=now)
        pending = await store.list(user_id, mode="LONGTERM", status="PENDING", limit=100)
        from backend.risk.paper_gate import for_mine
        pending = await for_mine(db, user_id, pending)
        if pending:
            pending.sort(key=lambda s: s["expires_at"])
            title, lines = alerts.split(proposals_text(pending, f"Good morning: {len(pending)} idea(s) for your account, from strategies proven on the AI account"))
            await alerts.alert(db, user_id, "ideas", title, lines)
    return did


async def _rotation(db, redis, user_id: str, now: datetime, morning: bool) -> None:
    """Morning: today's plan (Telegram), then trades. Later passes: trades only.
    Runs for a user with the autopilot on, or with rotation positions still open."""
    from backend import alerts
    from backend.autopilot import rotation

    try:
        enabled = (await PrefsStore(db).get(user_id)).get("autopilot_enabled")
        if not enabled and not await rotation.rotation_trades(db, user_id):
            return
        if morning:
            plan = await rotation.plan(db, redis, user_id, now)
            await alerts.alert(db, user_id, "money", f"AI plan · {plan['date']}", rotation.plan_text(plan))
        await rotation.rebalance(db, redis, user_id, now, buy=enabled)
    except Exception as exc:
        logger.exception("rotation failed for %s: %s", user_id, exc)


async def _catch_up(db, redis, day) -> None:
    from backend import scheduler

    try:
        await scheduler._run_locked(db, redis, pass_day=day)
    except Exception as exc:
        logger.exception("catch-up daily pass for %s failed: %s", day, exc)


async def _login_reminders(db, redis, now: datetime, get_adapter=None) -> None:
    """Weekdays 08:30 and again 09:05 IST: one Telegram message listing each
    broker not logged in today, with its login link. Without a session
    nothing runs that day: no holdings prices, journal, plan or AI trading."""
    from backend import alerts
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.registry import get_broker_adapter
    from backend.brokers.roles import LABELS

    local = now.astimezone(IST)
    if not is_trading_day(local.date()) or not (LOGIN_REMIND <= local.time() < SESSION_OPEN):
        return
    slot = "late" if local.time() >= LOGIN_REMIND_AGAIN else "early"
    get_adapter = get_adapter or get_broker_adapter
    for doc in await db["user_prefs"].find({"broker_roles": {"$exists": True, "$ne": {}}}).to_list(length=None):
        user_id = doc["user_id"]
        if not await redis.set(f"login:remind:{user_id}:{local.date()}:{slot}", _TOKEN, nx=True, px=86_400_000):
            continue
        lines, buttons = [], []
        for broker, role in sorted(doc["broker_roles"].items()):
            try:
                adapter = await get_adapter(broker, user_id, get_credential_store(), redis)
                if (await adapter.state()).value == "ACTIVE":
                    continue
                url = await adapter.login_url()
            except Exception as exc:
                logger.warning("login reminder: %s for %s failed: %s", broker, user_id, exc)
                continue
            name = f"{broker.replace('_', ' ').title()} ({LABELS.get(role, role)})"
            lines.append(name)
            if url:
                buttons.append([{"text": name, "url": url}])
        if lines:
            if len(buttons) < len(lines) and (row := alerts.open_button("/settings")):
                buttons.append(row)  # one Open row for the brokers without a login link
            await alerts.alert(db, user_id, "action", "Log in before 9:15", lines, buttons=buttons or None)


async def autorun_loop(db, redis) -> None:
    while True:
        try:
            result = await tick(db, redis)
            if result["started"] or result["stopped"]:
                logger.info("auto-run: %s", result)
            note = f"started {len(result['started'])}, stopped {len(result['stopped'])}"
            if result.get("idle"):
                note += f"; nothing started: {result['idle']}"
            await mark(redis, "autorun", True, note)
        except Exception as exc:
            logger.exception("auto-run tick failed: %s", exc)
            await mark(redis, "autorun", False, f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(INTERVAL_SECONDS)


def start(db, redis) -> asyncio.Task:
    return asyncio.create_task(autorun_loop(db, redis))
