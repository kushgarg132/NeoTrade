"""How often scored news pointed the right way: the bar every decision use of news reads.

    report   pure: outcome rows (joined with their item's source and model) ->
             cells, each a group x scope x key x impact bucket x horizon x
             measure, with n, hit rate, mean signed move and a day-block
             bootstrap t. Only items with |direction| >= MIN_DIRECTION count.
    build    reads `news_outcomes` + `news_items`, writes Mongo `news_accuracy`
             `{_id: "latest", as_of, cells}`
    loop     weekly in the ingest worker (leader only), via a Redis SET NX
    company_scan_ok   the N0.1 gate: company direction, 5d, clears HIT_BAR

Groups: `theme` (key = a theme or "all", impact = a bucket or "all"), `source`
and `model` (impact "all"). Measures are the prefixes outcomes.py writes:
`move` (vs Nifty from the scoring-time price), `pre_move` (vs Nifty from the
close before publication) and `sector_move` (vs the sector's other members).
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from backend.datalayer.outcomes import COLLECTION as OUTCOMES, _sign
from backend.engine.session import IST

logger = logging.getLogger(__name__)

COLLECTION = "news_accuracy"
HORIZONS = ("1d", "5d", "20d")
MEASURES = ("move", "pre_move", "sector_move")
MIN_DIRECTION = 0.5
THIN = 30
BOOT = 2000
DUE_KEY = "news:accuracy:due"
EVERY_SECONDS = 7 * 86400
SCAN_HORIZON, SCAN_MIN_N, HIT_BAR = "5d", 300, 0.52


def impact_bucket(impact: float) -> str:
    return "<5" if impact < 5 else "5-7" if impact < 7 else ">=7"


def _day(at: datetime) -> str:
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(IST).date().isoformat()


def _stats(points: list[tuple[str, float, bool]]) -> dict:
    """points: (IST day, signed move, hit). t resamples whole days, as
    forecast/study.py::adjusted_edge resamples months: same-day items move together."""
    n = len(points)
    by_day = defaultdict(lambda: [0.0, 0])
    for day, signed, _ in points:
        by_day[day][0] += signed
        by_day[day][1] += 1
    s = np.array([v[0] for v in by_day.values()])
    c = np.array([v[1] for v in by_day.values()])
    mean = float(s.sum() / c.sum())
    t = None
    if len(s) > 1:
        idx = np.random.default_rng(0).integers(0, len(s), (BOOT, len(s)))
        sd = (s[idx].sum(1) / c[idx].sum(1)).std(ddof=1)
        t = float(mean / sd) if sd > 0 else None
    return {"n": n, "hit": sum(p[2] for p in points) / n, "mean": mean, "t": t, "thin": n < THIN}


def report(rows: list[dict]) -> list[dict]:
    """rows: outcomes with scope, themes, impact, direction, published_at,
    source, model and the `{measure}_{horizon}` fields."""
    groups = defaultdict(list)
    for row in rows:
        direction = row.get("direction") or 0
        if abs(direction) < MIN_DIRECTION:
            continue
        scope, bucket, day = row.get("scope") or "", impact_bucket(row.get("impact") or 0), _day(row["published_at"])
        keys = [("theme", scope, theme, b) for theme in [*(row.get("themes") or []), "all"] for b in (bucket, "all")]
        keys += [("source", scope, row.get("source") or "unknown", "all"),
                 ("model", scope, row.get("model") or "unknown", "all")]
        for h in HORIZONS:
            for m in MEASURES:
                move = row.get(f"{m}_{h}")
                if move is None:
                    continue
                point = (day, move * _sign(direction), _sign(move) == _sign(direction))
                for key in keys:
                    groups[(*key, h, m)].append(point)
    return [{"group": g, "scope": scope, "key": key, "impact": impact, "horizon": h, "measure": m, **_stats(points)}
            for (g, scope, key, impact, h, m), points in sorted(groups.items())]


def _cell(report: dict, measure: str) -> Optional[dict]:
    return next((c for c in report.get("cells") or [] if c["group"] == "theme" and c["scope"] == "COMPANY"
                 and c["key"] == "all" and c["impact"] == "all" and c["horizon"] == SCAN_HORIZON
                 and c["measure"] == measure), None)


def company_scan_ok(report: Optional[dict]) -> bool:
    """Company news may make ideas again: 5d direction hit >= 52% over n >= 300,
    on `pre_move` once it has 300 rows, else `move`. Not wired yet (N0.1)."""
    cell = _cell(report or {}, "pre_move")
    if not cell or cell["n"] < SCAN_MIN_N:
        cell = _cell(report or {}, "move")
    return bool(cell) and cell["n"] >= SCAN_MIN_N and cell["hit"] >= HIT_BAR


async def build(db, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    fields = {"item_id": 1, "scope": 1, "themes": 1, "impact": 1, "direction": 1, "published_at": 1,
              **{f"{m}_{h}": 1 for m in MEASURES for h in HORIZONS}}
    rows = await db[OUTCOMES].find({"late": {"$ne": True}}, fields).to_list(length=None)
    items = {d["_id"]: d async for d in db["news_items"].find(
        {"_id": {"$in": list({r["item_id"] for r in rows})}}, {"source": 1, "model": 1})}
    for row in rows:
        item = items.get(row["item_id"], {})
        row["source"], row["model"] = item.get("source"), item.get("model")
    doc = {"as_of": now, "rows": len(rows), "cells": report(rows)}
    await db[COLLECTION].replace_one({"_id": "latest"}, doc, upsert=True)
    logger.info("news accuracy: %d cell(s) from %d outcome(s)", len(doc["cells"]), len(rows))
    return doc


async def loop(db, redis) -> None:
    if await redis.set(DUE_KEY, "1", ex=EVERY_SECONDS, nx=True):
        await build(db)
