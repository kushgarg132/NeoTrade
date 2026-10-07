"""`python -m backend.builder`: one weekly drafting run (backend/builder/draft.py), started by
the Friday daily pass as its own low-priority process. `--test <slug>` backtests just that draft."""
import asyncio
import logging
import sys
from datetime import datetime, timezone

from backend.builder.draft import run, test_one


async def _main(slug: str | None = None) -> None:
    from backend.database import db

    await db.connect_to_database()
    now = datetime.now(timezone.utc)
    print(await (test_one(db.db, db.redis, slug, now) if slug else run(db.db, db.redis, now)), flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = sys.argv[1:]
    if args[:1] == ["--test"] and len(args) < 2:
        print("usage: python -m backend.builder [--test <slug>]", file=sys.stderr)
        sys.exit(2)  # never the weekly job by accident
    asyncio.run(_main(args[1] if args[:1] == ["--test"] else None))
