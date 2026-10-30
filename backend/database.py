from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis
from backend.configs.settings import settings
import logging

logger = logging.getLogger(__name__)


def mongo_client(url: str, **kwargs) -> AsyncIOMotorClient:
    """Datetimes come back UTC-aware: Mongo stores UTC, and a naive value sent
    to the browser without an offset is read as IST, 5h30m early."""
    return AsyncIOMotorClient(url, tz_aware=True, tzinfo=timezone.utc, **kwargs)


# On LOCAL_MONGODB_URL when set. 2026-10-27: Atlas M0 hit its 512 MB cap (daily_bars, news_history*).
# 2026-10-30: M0 throttles to ~100 KB/s past its weekly transfer allowance, which made Today take 15 s;
# the big or often-read rest followed. Nothing joins these with Atlas collections ($lookup/$merge),
# which would not work across two servers.
LOCAL_COLLECTIONS = frozenset({
    "daily_bars", "news_history", "news_history_outcomes", "news_history_fetch",
    "news_items", "news_outcomes", "news_accuracy", "instruments", "strategy_backtests",
    "portfolio_snapshots", "stock_health",
})


class RoutedDatabase:
    """The Atlas database, except LOCAL_COLLECTIONS, which live on the VM's Mongo under the same names.
    `db[name]` and `db.name` route; anything else (command, list_collection_names...) is Atlas's."""

    def __init__(self, main, local):
        self._main, self._local = main, local

    def __getitem__(self, name):
        return (self._local if name in LOCAL_COLLECTIONS else self._main)[name]

    def __getattr__(self, name):
        return self[name] if name in LOCAL_COLLECTIONS else getattr(self._main, name)


class DatabaseManager:
    client: AsyncIOMotorClient = None
    local_client: AsyncIOMotorClient = None
    db = None
    redis: aioredis.Redis = None

    async def connect_to_database(self):
        logger.info("Connecting to MongoDB...")
        self.client = mongo_client(settings.MONGODB_URL, compressors="zlib")  # less of M0's transfer allowance
        self.db = self.client[settings.DATABASE_NAME]
        if settings.LOCAL_MONGODB_URL:
            self.local_client = mongo_client(settings.LOCAL_MONGODB_URL)
            self.db = RoutedDatabase(self.db, self.local_client[settings.DATABASE_NAME])
        logger.info("Connected to MongoDB.")

        logger.info("Connecting to Redis...")
        self.redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        logger.info("Connected to Redis.")

    async def close_database_connection(self):
        logger.info("Closing database connections...")
        if self.client:
            self.client.close()
        if self.local_client:
            self.local_client.close()
        if self.redis:
            await self.redis.close()
        logger.info("Database connections closed.")

db = DatabaseManager()

async def get_database():
    return db.db
