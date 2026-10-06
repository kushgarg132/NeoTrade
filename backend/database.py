from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis
from backend.configs.settings import settings
import logging

logger = logging.getLogger(__name__)


def mongo_client(url: str) -> AsyncIOMotorClient:
    """Datetimes come back UTC-aware: Mongo stores UTC, and a naive value sent
    to the browser without an offset is read as IST, 5h30m early."""
    return AsyncIOMotorClient(url, tz_aware=True, tzinfo=timezone.utc)


class DatabaseManager:
    client: AsyncIOMotorClient = None
    db = None
    redis: aioredis.Redis = None

    async def connect_to_database(self):
        logger.info("Connecting to MongoDB...")
        self.client = mongo_client(settings.MONGODB_URL)
        self.db = self.client[settings.DATABASE_NAME]
        logger.info("Connected to MongoDB.")

        logger.info("Connecting to Redis...")
        self.redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        logger.info("Connected to Redis.")

    async def close_database_connection(self):
        logger.info("Closing database connections...")
        if self.client:
            self.client.close()
        if self.redis:
            await self.redis.close()
        logger.info("Database connections closed.")

db = DatabaseManager()

async def get_database():
    return db.db
