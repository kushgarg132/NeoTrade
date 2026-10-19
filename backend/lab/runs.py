"""Every simulator writes a reproducible run record here (collection `lab_runs`).

`record` is best-effort: a failed insert is logged and returns None, never raises
into the simulator that called it.
"""

import hashlib
import logging
import os
import subprocess
from dataclasses import asdict
from datetime import date, datetime, timezone
from functools import lru_cache
from uuid import uuid4

import pandas as pd

from backend.lab.assumptions import Execution
from backend.lab.splits import Fold

logger = logging.getLogger(__name__)

COLLECTION = "lab_runs"


def fingerprint(frame: pd.DataFrame) -> str:
    """sha256 over sorted symbols, dates and closes rounded to 4 dp; column order independent."""
    f = frame.sort_index(axis=1)
    h = hashlib.sha256()
    h.update(",".join(map(str, f.columns)).encode())
    h.update(",".join(str(pd.Timestamp(d).date()) for d in f.index).encode())
    h.update(f.round(4).to_numpy(dtype="float64").tobytes())
    return h.hexdigest()


@lru_cache(maxsize=1)
def code_sha() -> str:
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5, check=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _fold_doc(f: Fold) -> dict:
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(f).items()}


class LabRunStore:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db[COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("kind", 1), ("name", 1), ("created_at", -1)])
        await self.collection.create_index("id", unique=True)

    async def record(self, *, kind: str, name: str, config: dict, execution: Execution,
                     window: tuple[date, date], fingerprint: str | None, folds: list[Fold],
                     metrics: dict, user_id: str = "system") -> str | None:
        try:
            run_id = uuid4().hex
            await self.collection.insert_one({
                "id": run_id, "kind": kind, "name": name, "config": config,
                "execution": asdict(execution), "window": [window[0].isoformat(), window[1].isoformat()],
                "fingerprint": fingerprint, "folds": [_fold_doc(f) for f in folds],
                "metrics": metrics, "code_sha": code_sha(), "user_id": user_id,
                "created_at": datetime.now(timezone.utc),
            })
            return run_id
        except Exception as exc:
            logger.warning("lab run %s/%s not recorded: %s", kind, name, exc)
            return None

    async def get(self, run_id: str) -> dict | None:
        return await self.collection.find_one({"id": run_id}, {"_id": 0})

    async def list(self, kind: str | None = None, name: str | None = None, limit: int = 50) -> list[dict]:
        q = {k: v for k, v in (("kind", kind), ("name", name)) if v is not None}
        return await self.collection.find(q, {"_id": 0}).sort([("created_at", -1), ("_id", -1)]).limit(limit).to_list(limit)
