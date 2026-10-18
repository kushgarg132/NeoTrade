"""Picks: today's setups with their measured base rates, stored before the
outcome is known, then scored once they mature (the forward record).

Runs in the 16:00 IST daily pass (`scheduler.run_daily_jobs`). Market-wide,
not per user; served admin-only (`routers/picks.py`) until the owner's SEBI
RA registration exists -- nothing here reaches Telegram, digests or chat.

Collections: `picks` (one doc per signal day/setup/symbol, `_id`
"<date>:<setup>:<symbol>") and `picks_study` (`_id` "latest": per-setup
stats and walk-forward calibration from the last run).
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from backend.datalayer import bars
from backend.forecast import setups, study

logger = logging.getLogger(__name__)

PICKS = "picks"
STUDY = "picks_study"
MAX_PICKS = 10
MIN_FORWARD = 100  # scored forward picks before the forward record counts
# Every stored bar (bars.DEEP_START, 2009 on): ~850k bars, a ~15s read and
# ~4s of study on the VM (estimated 2026-10-17 from 280k bars read in 4.6s;
# the study measured 1.3s over 6 years, 3.9s since 2009).
HISTORY_START = date.fromisoformat(bars.DEEP_START)
CAVEATS = [
    "Survivorship: the universe is today's stock list, so names that were delisted or dropped out are missing "
    "from history, which flatters past returns.",
    "Every number is a base rate measured over this setup's past events (net of delivery charges), "
    "not a forecast for this particular stock.",
    "Past base rates can change; the walk-forward table shows how well they held out of sample.",
]


def compute(t: dict) -> tuple[dict, list[dict]]:
    """(per-setup results, today's picks) from a wide table. Pure."""
    results, fires = study.run(t, setups.SETUPS)
    days = t["close"].index
    last = len(days) - 1
    picks = []
    for s in setups.SETUPS:
        r = results[s.name]
        if r["n"] < study.MIN_N:
            continue
        for symbol in fires[s.name].columns:
            col = fires[s.name][symbol].to_numpy()
            if not study.kept(col, s.horizon)[-1:] == [last]:
                continue  # did not fire today, or today sits inside an open event's window
            day = days[last]
            picks.append({
                "_id": f"{day.date()}:{s.name}:{symbol}",
                "date": day.date().isoformat(), "symbol": symbol, "setup": s.name, "label": s.label,
                "horizon": s.horizon,
                # weekdays only: an exchange holiday pushes the real exit later
                "due_date": (day + pd.offsets.BDay(s.horizon + 1)).date().isoformat(),
                "entry_ref": float(t["close"][symbol].iat[last]),
                "expected": {"median": r["median"], "p10": r["p10"], "p90": r["p90"]},
                "p_up": r["p_up"], "p_beat_nifty": r["p_beat_nifty"], "n": r["n"],
                "median_excess": r["median_excess"], "edge": r["walk_forward"]["edge"],
                "explanation": s.explain(t, symbol, day),
                "strength": float(col[last]),
            })
    picks.sort(key=lambda p: (p["median_excess"] * p["p_beat_nifty"], p["strength"]), reverse=True)
    return results, picks[:MAX_PICKS]


def score(t: dict, pick: dict) -> Optional[dict]:
    """The pick's outcome once its exit bar exists, else None."""
    days = t["close"].index
    day = pd.Timestamp(pick["date"])
    if day not in days or pick["symbol"] not in t["close"].columns:
        return None
    o = study.outcome(t, pick["symbol"], days.get_loc(day), pick["horizon"])
    if o is None:
        return None
    _, exit_day, gross, net, nifty = o
    return {"exit_date": exit_day.date().isoformat(), "gross": gross, "net": net, "nifty": nifty,
            "won": net > 0, "beat_nifty": net > nifty}


def forward(scored: list[dict]) -> dict:
    """Predicted P(up) in 10-point buckets against the realised win rate."""
    buckets: dict[float, list] = {}
    for p in scored:
        buckets.setdefault(min(int(p["p_up"] * 10), 9) / 10, []).append(p)
    rows = [{
        "bucket": f"{b:.0%}–{b + 0.1:.0%}", "n": len(ps),
        "predicted": sum(p["p_up"] for p in ps) / len(ps),
        "realised": sum(p["outcome"]["won"] for p in ps) / len(ps),
    } for b, ps in sorted(buckets.items())]
    n = len(scored)
    return {
        "n": n, "status": "unproven" if n < MIN_FORWARD else "measured", "buckets": rows,
        "win_rate": sum(p["outcome"]["won"] for p in scored) / n if n else None,
        "beat_nifty_rate": sum(p["outcome"]["beat_nifty"] for p in scored) / n if n else None,
    }


CALIBRATION_GAP = 0.05  # live needs predicted P(up) within 5 points of the realised win rate


def live_refusal(scored: list[dict]) -> Optional[str]:
    """Why the forward record does not yet allow real money for Picks, or
    None: at least MIN_FORWARD scored picks, calibrated within
    CALIBRATION_GAP (bucket gaps weighted by count) and a positive mean net
    excess over the Nifty."""
    record = forward(scored)
    n = record["n"]
    if n < MIN_FORWARD:
        return f"Picks has {n} scored picks; real money needs {MIN_FORWARD}."
    gap = sum(abs(b["predicted"] - b["realised"]) * b["n"] for b in record["buckets"]) / n
    if gap > CALIBRATION_GAP:
        return f"Picks is {gap:.0%} off calibration; real money needs {CALIBRATION_GAP:.0%} or less."
    excess = sum(p["outcome"]["net"] - p["outcome"]["nifty"] for p in scored) / n
    if excess <= 0:
        return f"Picks averages {excess:+.2%} against the Nifty; real money needs a positive excess."
    return None


async def load(db, now: datetime) -> Optional[dict]:
    today = bars.today_ist(now)
    universe = set(await db[bars.BARS].distinct("symbol")) | {bars.NIFTY}
    frames = await bars.read(db, universe, HISTORY_START, today)
    if bars.NIFTY not in frames or len(frames) < 2:
        return None
    return setups.table(frames)


async def ensure_indexes(db) -> None:
    """`date` serves /picks (latest day, history), `outcome` the unscored and scored scans."""
    try:
        await db[PICKS].create_index([("date", -1)])
        await db[PICKS].create_index("outcome")
    except Exception as exc:  # startup must not fail on it
        logger.error("picks indexes not created: %s", exc)


async def run(db, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    t = await load(db, now)
    if t is None:
        return {"picks": 0, "scored": 0}
    results, today = await asyncio.to_thread(compute, t)
    await db[STUDY].replace_one({"_id": "latest"}, {"as_of": now, "setups": list(results.values())}, upsert=True)

    known = set(await db[PICKS].distinct("_id", {"_id": {"$in": [p["_id"] for p in today]}}))
    new = [{**p, "created_at": now, "outcome": None} for p in today if p["_id"] not in known]
    if new:
        await db[PICKS].insert_many(new)

    scored = 0
    async for pick in db[PICKS].find({"outcome": None}):
        result = score(t, pick)
        if result:
            await db[PICKS].update_one({"_id": pick["_id"]}, {"$set": {"outcome": result, "scored_at": now}})
            scored += 1
    logger.info("picks: %d new, %d scored", len(new), scored)
    return {"picks": len(new), "scored": scored}
