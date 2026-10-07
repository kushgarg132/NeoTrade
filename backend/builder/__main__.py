"""`python -m backend.builder`: one weekly drafting run (backend/builder/draft.py), started by
the Friday daily pass as its own low-priority process."""
import asyncio
import logging
from datetime import datetime, timezone

from backend.builder.draft import run


async def _main() -> None:
    from backend.database import db

    await db.connect_to_database()
    print(await run(db.db, db.redis, datetime.now(timezone.utc)), flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
