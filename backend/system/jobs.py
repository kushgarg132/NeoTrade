"""Last run of each background job, for the handbook's live panels.

`mark` writes `job:last:<name>` = {at, ok, note} after each run or tick. It
never raises: a Redis hiccup must not break the job it is recording."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KEY = "job:last:{}"
NOTE_LIMIT = 2000
DAILY_PASS = "daily_pass"
DATA_QUALITY = "data_quality"  # backend/system/data_quality.py, after the daily pass
BUILDER = "strategy_builder"  # backend/builder/draft.py, Friday nights
LOOPS = ("guardrail_monitor", "paper_orders", "autorun", "telegram")


async def mark(redis, name: str, ok: bool, note: str = "") -> None:
    if redis is None:
        return
    try:
        await redis.hset(KEY.format(name), mapping={
            "at": datetime.now(timezone.utc).isoformat(), "ok": "1" if ok else "0", "note": note[:NOTE_LIMIT],
        })
    except Exception as exc:
        logger.warning("could not record %s run: %s", name, exc)


async def last_runs(redis, names) -> dict:
    out = {}
    for name in names:
        raw = await redis.hgetall(KEY.format(name))
        raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
               for k, v in (raw or {}).items()}
        out[name] = {"at": raw["at"], "ok": raw.get("ok") == "1", "note": raw.get("note", "")} if raw.get("at") else None
    return out
