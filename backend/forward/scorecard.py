"""Per-source/name forward stats, the one "proven" rule, and how it compares
with each source's existing money gate."""

import logging
import math
import time
from collections import defaultdict
from typing import Optional

from backend.forward.store import ForwardStore

logger = logging.getLogger(__name__)
MIN_N = 100
MIN_T = 2.0
MAX_GAP = 0.05
NEWS_MIN_N = 20
CACHE_SECONDS = 60
_cache: tuple = (0.0, None)  # (monotonic time, rows)


def stats(records: list[dict]) -> dict:
    records = [r for r in records if "excess" in (r.get("outcome") or {})]  # skip voids defensively
    outs = [r["outcome"] for r in records]
    n = len(outs)
    excess = [o["excess"] for o in outs]
    mean_excess = sum(excess) / n if n else None
    t = None
    if n >= 2:
        sd = math.sqrt(sum((x - mean_excess) ** 2 for x in excess) / (n - 1))
        t = mean_excess / (sd / math.sqrt(n)) if sd > 0 else None
    ps = [(r["predicted"]["p_up"], bool(r["outcome"]["won"])) for r in records
          if (r.get("predicted") or {}).get("p_up") is not None]
    return {
        "n": n,
        "mean_net": sum(o["net"] for o in outs) / n if n else None,
        "mean_excess": mean_excess,
        "t": t,
        "hit_rate": sum(bool(o["won"]) for o in outs) / n if n else None,
        "brier": sum((p - w) ** 2 for p, w in ps) / len(ps) if ps else None,
        "calibration_gap": abs(sum(p for p, _ in ps) / len(ps) - sum(w for _, w in ps) / len(ps)) if ps else None,
    }


def label(s: dict) -> dict:
    gap = s.get("calibration_gap")
    ok = (s["n"] >= MIN_N and (s.get("mean_excess") or 0) > 0 and (s.get("t") or 0) >= MIN_T
          and (gap is None or gap <= MAX_GAP))
    return {"label": "proven" if ok else "unproven", "progress": min(s["n"], MIN_N)}


async def _gate(db, source: str, name: str, admin: Optional[tuple] = None) -> Optional[bool]:
    """Does the source's existing money gate pass this name? None when unknown."""
    try:
        if source == "picks":
            from backend.forecast.picks import LONG_SUFFIX, PICKS, live_refusal

            if name.endswith(LONG_SUFFIX):
                return None  # paper-only twin: no live gate exists for it

            scored = await db[PICKS].find({"setup": name, "outcome": {"$ne": None}}).to_list(length=None)
            return live_refusal(scored) is None
        if source in ("engine", "suggestion"):
            from backend.prefs import PrefsStore
            from backend.risk import paper_gate

            if admin is None:  # (admin id, account size), looked up once per scorecard call
                admin = await _admin(db)
            if not admin:
                return None
            return name in await paper_gate.proven_strategies(db, admin[0], {name}, admin[1])
        if source == "news":
            w = await db["news_theme_weights"].find_one({"_id": name})
            return bool(w) and w["weight"] > 1 and w["n"] >= NEWS_MIN_N
    except Exception as exc:
        logger.warning("forward gate lookup failed for %s:%s: %s", source, name, exc)
    return None


async def _admin(db) -> Optional[tuple]:
    from backend.prefs import PrefsStore

    row = await db["users"].find_one({"role": "admin"}, {"id": 1})
    return (row["id"], (await PrefsStore(db).get(row["id"]))["account_size"]) if row else None


async def scorecard(db, force: bool = False) -> list[dict]:
    """Cached 60 s in-process: the badge hook calls this on every page load."""
    global _cache
    at, rows = _cache
    if not force and rows is not None and time.monotonic() - at < CACHE_SECONDS:
        return rows
    rows = await _scorecard(db)
    _cache = (time.monotonic(), rows)
    return rows


async def _scorecard(db) -> list[dict]:
    try:
        admin = await _admin(db)
    except Exception as exc:
        logger.warning("forward admin lookup failed: %s", exc)
        admin = None
    groups = defaultdict(list)
    for r in await ForwardStore(db).scored():
        groups[(r["source"], r["name"])].append(r)
    rows = []
    for (source, name), group in sorted(groups.items()):
        s = stats(group)
        lab = label(s)
        gate = await _gate(db, source, name, admin)
        rows.append({"source": source, "name": name, **s, **lab, "gate": gate,
                     "disagrees": None if gate is None else gate != (lab["label"] == "proven")})
    return rows
