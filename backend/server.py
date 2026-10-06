import asyncio
import sys
import os
import uvicorn

# Add project root to sys.path to allow imports from configs, mcp_tools, etc.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.auth.dependency import get_current_user
from backend.auth.refresh_store import RefreshTokenStore
from backend.auth.store import UserStore
from backend.configs.settings import settings
from backend.runs import RunStore
from backend.suggestions.store import SuggestionStore
from backend.prefs import PrefsStore
from backend.journal.store import JournalStore
from backend.guardrails.store import GuardrailStore
from backend.guardrails import monitor as guardrail_monitor
from backend.engine import paper_orders
from backend.guardrails import telegram_bot
from backend.engine import autorun
from backend import broadcast
from backend import scheduler
from backend.ws.hub import hub, handle_broadcast_event
from backend.ws import pump as ws_pump
from backend.ws import routes as ws_routes
from backend.configs.logging_config import setup_logging
from backend.database import db
from backend.instruments.master import InstrumentMaster
from backend.app_settings import AppSettingsStore
from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
from backend.instruments.loader import (
    SeedFileSource,
    refresh_instruments,
    refresh_from_free_public_sources,
)

# Setup Logging
logger = setup_logging()
from backend.components.analyst import news
from backend.components.quant import price, trend, support, volume
from backend.components.risk import risk
from backend.components.master import stock_info
from backend.routers import scanner


# Session tokens ride the socket URL (?token=); keep them out of the access log.
from backend import log_redaction  # noqa: E402

log_redaction.install()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for NeoTrade Platform",
    version=settings.VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import auth as auth_router
app.include_router(auth_router.router, prefix=settings.API_PREFIX, tags=["Auth"])

# Database Events
_BACKGROUND: set = set()  # strong refs, so a startup task is not garbage-collected


async def _expand_instruments(master) -> None:
    try:
        free_count = await refresh_from_free_public_sources(master)
        if free_count:
            logger.info(f"Instrument master expanded from free NSE/BSE lists: {free_count} upserted.")
    except Exception as exc:
        logger.warning(f"free NSE/BSE instrument refresh failed: {exc}")


async def _heartbeat(redis) -> None:
    """Keeps worker:alive:<boot id> fresh while this process lives (runs.py)."""
    from backend.runs import ALIVE_KEY, ALIVE_TTL_SECONDS, BOOT_ID

    while redis is not None:
        try:
            await redis.set(ALIVE_KEY.format(BOOT_ID), "1", ex=ALIVE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("worker heartbeat failed: %s", exc)
        await asyncio.sleep(ALIVE_TTL_SECONDS // 3)


@app.on_event("startup")
async def startup_db_client():
    logger.info("Starting up NeoTrade API...")
    await db.connect_to_database()
    logger.info("Database connected.")

    hub.attach_redis(db.redis)
    from backend.routers.trading import handle_cancel_broadcast
    asyncio.create_task(broadcast.listen(db.redis, {
        "ws:events": handle_broadcast_event,
        "runs:cancel": handle_cancel_broadcast,
    }))

    master = InstrumentMaster(db.db)
    await master.ensure_indexes()
    await UserStore(db.db).ensure_indexes()
    await RefreshTokenStore(db.db).ensure_indexes()
    count = await refresh_instruments(SeedFileSource(), master, only_new=True)
    logger.info(f"Instrument master seeded: {count} upserted.")
    # NSE/BSE list downloads plus thousands of upserts can take minutes; run
    # them in the background so a deploy never waits on them (it was a ~4
    # minute 502 whenever the 20-hour marker had expired).
    _BACKGROUND.add(asyncio.create_task(_expand_instruments(master)))
    # No Kite refresh here any more: credentials are per-user, and at startup
    # there is no user in scope. It happens when someone connects their broker
    # (see routers/broker.py), which is also when a fresh daily token exists.

    await SuggestionStore(db.db).ensure_indexes()
    await PrefsStore(db.db).ensure_indexes()
    await JournalStore(db.db).ensure_indexes()
    await db.db["portfolio_snapshots"].create_index([("user_id", 1), ("at", -1)])
    await GuardrailStore(db.db).ensure_indexes()
    from backend.chat.actions import ChatActionStore
    await ChatActionStore(db.db).ensure_indexes()
    await BrokerCredentialStore(db.db, fernet_from_settings()).ensure_indexes()
    # The paper ledger and live orders had indexes defined but never created:
    # nothing stopped duplicate (user, symbol) positions from concurrent upserts.
    try:
        from backend.engine.execution.live_order_store import LiveOrderStore
        from backend.engine.persistence import LedgerStore

        await LedgerStore(db.db, user_id="").ensure_indexes()
        await LiveOrderStore(db.db).ensure_indexes()
        await db.db["paper_limit_orders"].create_index([("user_id", 1), ("status", 1)])
    except Exception as exc:
        logger.error("ledger indexes not created: %s", exc)
    await AppSettingsStore(db.db).load_into_cache()

    # Post-close scan, sentiment refresh and suggestion expiry.
    scheduler.start(db.db, db.redis)
    # Live prices and P&L for whoever has a socket open.
    ws_pump.start(db.db)
    # The user's own limits, checked against their broker once a minute in session.
    guardrail_monitor.start(db.db, db.redis)
    # Resting paper limit orders from the order ticket: fill on cross, expire at 15:30.
    paper_orders.start(db.db)
    # Linked Telegram chats are an authenticated client of the same AI and
    # proposal flow as the web widget; this is inbound polling, not a webhook.
    telegram_bot.start(db.db, db.redis)

    # An asyncio.Task cannot outlive the process that created it, so any run
    # still marked RUNNING belongs to a previous life of this container.
    runs = RunStore(db.db)
    await runs.ensure_indexes()
    # This worker's heartbeat first, so the sweep below (and the other
    # worker's) never mistakes this process's runs for orphans.
    _BACKGROUND.add(asyncio.create_task(_heartbeat(db.redis)))
    orphaned = await runs.close_orphaned(db.redis)
    if orphaned:
        logger.info(f"Closed {orphaned} orphaned trading run(s) from a previous process.")

    # Daily intraday paper run for users who turned it on. Started after the
    # orphan sweep so this worker's own first run is not swept with the rest.
    autorun.start(db.db, db.redis)

@app.on_event("shutdown")
async def shutdown_db_client():
    # A clean stop drops this worker's alive key at once, so the next
    # worker's sweep sees its runs as gone instead of waiting out the TTL.
    try:
        from backend.runs import ALIVE_KEY, BOOT_ID
        if db.redis is not None:
            await db.redis.delete(ALIVE_KEY.format(BOOT_ID))
    except Exception as exc:
        logger.warning("could not clear worker heartbeat: %s", exc)
    logger.info("Shutting down NeoTrade API...")
    await db.close_database_connection()
    logger.info("Database disconnected.")

# Include Routers
app.include_router(news.router, prefix=settings.API_PREFIX, tags=["News"], dependencies=[Depends(get_current_user)])
app.include_router(price.router, prefix=settings.API_PREFIX, tags=["Market Data"], dependencies=[Depends(get_current_user)])
app.include_router(support.router, prefix=settings.API_PREFIX, tags=["Technical Analysis"], dependencies=[Depends(get_current_user)])
app.include_router(trend.router, prefix=settings.API_PREFIX, tags=["Technical Analysis"], dependencies=[Depends(get_current_user)])
app.include_router(volume.router, prefix=settings.API_PREFIX, tags=["Technical Analysis"], dependencies=[Depends(get_current_user)])
app.include_router(risk.router, prefix=settings.API_PREFIX, tags=["Risk"], dependencies=[Depends(get_current_user)])
app.include_router(stock_info.router, prefix=settings.API_PREFIX, tags=["Market Data"], dependencies=[Depends(get_current_user)])
app.include_router(scanner.router, prefix=settings.API_PREFIX, tags=["Scanner"], dependencies=[Depends(get_current_user)])

# Agents Router
from backend.routers import agents

app.include_router(agents.router, prefix=f"{settings.API_PREFIX}/agents", tags=["Agents"], dependencies=[Depends(get_current_user)])
from backend.routers import chat_actions
app.include_router(chat_actions.router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
from backend.routers import orders
app.include_router(orders.router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])

from backend.routers import settings as settings_router
app.include_router(settings_router.router, prefix=settings.API_PREFIX, tags=["Settings"], dependencies=[Depends(get_current_user)])
from backend.routers import profile as profile_router
app.include_router(profile_router.router, prefix=settings.API_PREFIX, tags=["Profile"], dependencies=[Depends(get_current_user)])
from backend.routers import today as today_router
app.include_router(today_router.router, prefix=settings.API_PREFIX, tags=["Today"], dependencies=[Depends(get_current_user)])
from backend.routers import plan as plan_router
app.include_router(plan_router.router, prefix=settings.API_PREFIX, tags=["Plan"], dependencies=[Depends(get_current_user)])

from backend.routers import market_data
from backend.routers import options as options_router
from backend.routers import watchlist
from backend.routers import trading
from backend.routers import suggestions
from backend.routers import analytics
from backend.routers import broker
from backend.routers import journal
from backend.routers import guardrails as guardrails_router
from backend.routers import portfolio as portfolio_router

app.include_router(market_data.router, prefix=settings.API_PREFIX, tags=["Market Data"], dependencies=[Depends(get_current_user)])
app.include_router(options_router.router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])
app.include_router(watchlist.router, prefix=settings.API_PREFIX, tags=["Watchlist"], dependencies=[Depends(get_current_user)])
app.include_router(trading.router, prefix=settings.API_PREFIX, tags=["Trading"], dependencies=[Depends(get_current_user)])
app.include_router(suggestions.router, prefix=settings.API_PREFIX, tags=["Suggestions"], dependencies=[Depends(get_current_user)])
app.include_router(analytics.router, prefix=settings.API_PREFIX, tags=["Analytics"], dependencies=[Depends(get_current_user)])
app.include_router(broker.router, prefix=settings.API_PREFIX, tags=["Broker"], dependencies=[Depends(get_current_user)])
app.include_router(journal.router, prefix=settings.API_PREFIX, tags=["Journal"], dependencies=[Depends(get_current_user)])
app.include_router(guardrails_router.router, prefix=settings.API_PREFIX, tags=["Guardrails"], dependencies=[Depends(get_current_user)])
app.include_router(portfolio_router.router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])

# The socket authenticates its own handshake (see backend/ws/routes.py): the
# HTTP bearer dependency cannot run on a WebSocket upgrade.
app.include_router(ws_routes.router, prefix=settings.API_PREFIX, tags=["Live"])

@app.get("/docs", include_in_schema=False)
async def redirect_docs():
    return RedirectResponse(url=f"{settings.API_PREFIX}/docs")

@app.get("/redoc", include_in_schema=False)
async def redirect_redoc():
    return RedirectResponse(url=f"{settings.API_PREFIX}/redoc")

@app.head("/")
@app.get("/")
async def root():
    return {"message": "NeoTrade API is running"}


@app.get("/health")
async def health():
    """Seconds since each ingest loop last finished a pass
    (backend/datalayer/worker.py); `ingest` is empty when it is down."""
    from backend.datalayer.worker import heartbeat_ages

    try:
        ingest = await heartbeat_ages(db.redis)
    except Exception as exc:
        logger.warning("health: heartbeat read failed: %s", exc)
        ingest = None
    return {"api": "ok", "ingest": ingest}

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=settings.SERVER_PORT, reload=True)
