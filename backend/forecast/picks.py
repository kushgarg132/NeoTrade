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

from backend.core.market_calendar import add_trading_days, is_trading_day, trading_days_between
from backend.datalayer import bars
from backend.forecast import setups, similar, study

logger = logging.getLogger(__name__)

PICKS = "picks"
STUDY = "picks_study"
MAX_PICKS = 10  # per setup: a global cap let one setup's month-start fires crowd out another's (1 Oct 2026)
MIN_FORWARD = 100  # scored forward picks before the forward record counts
# Every stored bar (bars.DEEP_START, 2009 on): ~850k bars, a ~15s read and
# ~4s of study on the VM (estimated 2026-10-17 from 280k bars read in 4.6s;
# the study measured 1.3s over 6 years, 3.9s since 2009).
HISTORY_START = date.fromisoformat(bars.DEEP_START)
CAVEATS = [
    "Survivorship: the universe is today's stock list, so names that were delisted or dropped out are missing "
    "from history, which flatters past returns.",
    "Every number is a base rate measured over past events (net of delivery charges): this setup's overall, "
    "or, where testing showed it helps, the stock's most similar past setups.",
    "Past base rates can change; the walk-forward table shows how well they held out of sample.",
]


ATR_DAYS = 14
STOP_ATR = 2.0  # a stop no further than this many ATRs below entry


def _atr(t: dict, symbol: str, last: int) -> Optional[float]:
    """Average true range over the ATR_DAYS bars to `last`, in rupees; None without the bars."""
    h, l, c = (t[k][symbol].iloc[max(last - ATR_DAYS, 0):last + 1] for k in ("high", "low", "close"))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1).iloc[1:]
    v = float(tr.mean()) if len(tr) else float("nan")
    return v if v == v and v > 0 else None


def levels(p: dict) -> Optional[dict]:
    """Price levels for a pick, from its stored range: entry zone (entry_ref to ENTRY_ZONE above), target
    (median), stretch (p90), stop (the tighter of p10 and STOP_ATR x ATR below entry; always below entry) and
    reward:risk. The range is the stock's own (`range_stock`) when the backend chose one. Pure."""
    e, x = p.get("entry_ref"), p.get("expected") or {}
    if not e or x.get("median") is None:
        return None
    rs = x.get("range_stock") or {}
    lo, hi = rs.get("p10", x.get("p10")), rs.get("p90", x.get("p90"))
    stops = [e * (1 + lo)] if lo is not None and lo < 0 else []
    if p.get("atr"):
        stops.append(e - STOP_ATR * p["atr"])
    stop = max(stops) if stops else None
    target = e * (1 + x["median"]) if x["median"] > 0 else None
    r2 = lambda v: None if v is None else round(v, 2)
    return {"entry_zone": [r2(e), r2(e * (1 + ENTRY_ZONE))], "target": r2(target),
            "stretch": r2(e * (1 + hi)) if hi is not None and hi > 0 else None, "stop": r2(stop),
            "reward_risk": round((target - e) / (e - stop), 2) if target and stop and stop < e else None}


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
        ev = similar.event_features(t, study.events(t, s, fires[s.name]), fires[s.name])
        r["similar"] = similar.validate(ev)
        r["vol_range"] = vr = similar.validate_range(ev, s.horizon)
        full = ev[ev["exit"] < days[last]]
        frames = similar._frames(t)
        pool = ev[ev["exit"] < days[last]] if r["similar"]["personalised"] else None
        for symbol in fires[s.name].columns:
            col = fires[s.name][symbol].to_numpy()
            if not study.kept(col, s.horizon)[-1:] == [last]:
                continue  # did not fire today, or today sits inside an open event's window
            day = days[last]
            x = similar.features(t, symbol, last, float(col[last]), frames)
            f = similar.forecast(pool, x) if pool is not None and x is not None else None
            base = {"median": r["median"], "p10": r["p10"], "p90": r["p90"],
                    "excess": {"median": r["median_excess"], "p10": r["excess_p10"], "p90": r["excess_p90"]}}
            rs = None
            if vr["chosen"] and x is not None and len(full) >= similar.MIN_POOL:
                lo, hi = similar.scaled_range(full, float(x[0]), s.horizon, centered=vr["chosen"] == "vol_scaled")
                rs = {"p10": lo, "p90": hi, "method": vr["chosen"]}
            picks.append({
                "_id": f"{day.date()}:{s.name}:{symbol}",
                "date": day.date().isoformat(), "symbol": symbol, "setup": s.name, "label": s.label,
                "horizon": s.horizon,
                "due_date": add_trading_days(day.date(), s.horizon + 1).isoformat(),
                "entry_ref": float(t["close"][symbol].iat[last]),
                "atr": _atr(t, symbol, last),
                "expected": {**({k: f[k] for k in ("median", "p10", "p90", "excess")} if f else base),
                             **({"range_stock": rs} if rs else {})},
                "p_up": f["p_up"] if f else r["p_up"],
                "p_beat_nifty": f["p_beat_nifty"] if f else r["p_beat_nifty"], "n": r["n"],
                "median_excess": f["excess"]["median"] if f else r["median_excess"],
                "edge": r["adjusted"]["edge"],  # baseline-adjusted, as the grade (walk_forward["edge"] has no baseline)
                "forecast": "similar" if f else "setup", "similar_n": f["n"] if f else None,
                "features": dict(zip(similar.FEATURES, map(float, x))) if x is not None else None,
                "explanation": s.explain(t, symbol, day),
                "strength": float(col[last]),
            })
    picks.sort(key=rank_key, reverse=True)
    return results, cap_per_setup(picks)


def cap_per_setup(picks: list[dict]) -> list[dict]:
    """The first MAX_PICKS of each setup, order kept. Pure."""
    count: dict[str, int] = {}
    out = []
    for p in picks:
        count[p["setup"]] = count.get(p["setup"], 0) + 1
        if count[p["setup"]] <= MAX_PICKS:
            out.append(p)
    return out


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


def rank_key(p: dict) -> tuple:
    """Best first when sorted with reverse=True (the Picks page order)."""
    return p["median_excess"] * p["p_beat_nifty"], p["strength"]


MIN_P_BEAT = 0.55         # a label now ("beats_nifty_odds"), not a filter
ENTRY_ZONE = 0.03         # an earlier pick up to this far above its signal price is still a fair entry
MAX_SHOWN = 3             # per grade
B_MIN_T = 1.0
GRADES = ("A", "B", "C")
# What each grade means, from the setup's adjusted out-of-sample excess over the average stock
# (`study.adjusted_edge`, stored in picks_study). Every number there is already net of charges.
GRADE_TEXT = {
    "A": "Proven: beat the average stock out of sample (t >= 2)",
    "B": "Promising: ahead of the average stock out of sample, not yet proven",
    "C": "Unproven: no edge over the average stock so far",
}


def setup_grades(study_doc: dict) -> dict[str, str]:
    """setup -> "A" (adjusted edge), "B" (excess > 0 and t >= B_MIN_T) or "C". A study without `adjusted`
    grades everything C."""
    out = {}
    for s in (study_doc or {}).get("setups", []):
        a = s.get("adjusted") or {}
        ex, t = a.get("excess"), a.get("t")
        out[s["setup"]] = "A" if a.get("edge") else "B" if ex is not None and ex > 0 and t is not None and t >= B_MIN_T else "C"
    return out


def _trading_days_after(a: date, b: date) -> int:
    """Trading days in (a, b]."""
    return max(len(trading_days_between(a, b)) - (1 if is_trading_day(a) else 0), 0) if b > a else 0


def serve(today_picks: list[dict], older: list[dict], prices: dict[str, float], today: date, grades: dict) -> dict:
    """The served list from every stored candidate (storage is untouched): each pick still before its due
    date, graded by its setup (`setup_grades`), the newest per setup and symbol, at most MAX_SHOWN per grade,
    A first; within a grade, picks still in their entry zone first, then by median excess and P(beat NIFTY).
    `today_picks` are the latest pass, `older` earlier ones, `today` the real IST date. Pure."""
    fired = date.fromisoformat(today_picks[0]["date"]) if today_picks else today
    exp = lambda p: bool(setups.BY_NAME[p["setup"]].experimental) if p["setup"] in setups.BY_NAME else False
    rows, seen = [], set()
    for p in today_picks:
        seen.add((p["setup"], p["symbol"]))
        rows.append({**p, "days_since": 0, "price_now": None, "move_since_entry": None})
    for p in sorted(older, key=lambda p: p["date"], reverse=True):
        d = date.fromisoformat(p["date"])
        if d >= fired or today >= date.fromisoformat(p["due_date"]) or (p["setup"], p["symbol"]) in seen:
            continue
        seen.add((p["setup"], p["symbol"]))
        now = prices.get(p["symbol"])
        rows.append({**p, "days_since": _trading_days_after(d, fired), "price_now": now,
                     "move_since_entry": now / p["entry_ref"] - 1 if now and p.get("entry_ref") else None})
    for r in rows:
        move = r["move_since_entry"]
        r.update({"fired_on": r["date"], "experimental": exp(r), "grade": grades.get(r["setup"], "C"), "levels": levels(r),
                  "missed_entry": move is not None and move > ENTRY_ZONE,
                  "beats_nifty_odds": r["p_beat_nifty"] >= MIN_P_BEAT,
                  "days_left": _trading_days_after(today, date.fromisoformat(r["due_date"]))})
    rows.sort(key=lambda r: (r["grade"], r["missed_entry"], -r["median_excess"], -r["p_beat_nifty"]))
    # One row per stock: two setups on the same name (rs_leaders at 20 and 60 days) show once, the better-graded.
    once = set()
    rows = [r for r in rows if not (r["symbol"] in once or once.add(r["symbol"]))]
    shown, reasons, count = [], [], 0
    for g in GRADES:
        of_grade = [r for r in rows if r["grade"] == g]
        shown += of_grade[:MAX_SHOWN]
        if len(of_grade) > MAX_SHOWN:
            count += len(of_grade) - MAX_SHOWN
            reasons.append(f"{len(of_grade) - MAX_SHOWN} more grade {g} hidden: top {MAX_SHOWN} per grade")
    return {"shown": shown, "hidden_count": count, "hidden_reason": "; ".join(reasons), "grades": grades,
            "grade_text": GRADE_TEXT}


def forward(scored: list[dict]) -> dict:
    """Predicted P(up) in 10-point buckets against the realised win rate. Backfilled picks (recomputed
    after the fact, `backfill`) are not forward picks and are left out."""
    scored = [p for p in scored if not p.get("backfilled")]
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
    scored = [p for p in scored if not p.get("backfilled")]  # never real-money evidence
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
    from backend.forecast import members

    t = setups.table(frames)
    t["member"] = members.mask(t["close"].index, t["close"].columns)  # no survivorship: each day's own index
    return t


async def ensure_indexes(db) -> None:
    """`date` serves /picks (latest day, history), `outcome` the unscored and scored scans."""
    try:
        await db[PICKS].create_index([("date", -1)])
        await db[PICKS].create_index("outcome")
    except Exception as exc:  # startup must not fail on it
        logger.error("picks indexes not created: %s", exc)


async def _record_runs(db, t: dict, results: dict) -> None:
    """One best-effort lab run per setup (event stats + walk-forward)."""
    try:
        from backend.lab.assumptions import DEFAULT
        from backend.lab.runs import LabRunStore, fingerprint

        days = t["close"].index
        fp = await asyncio.to_thread(fingerprint, t["close"])
        store = LabRunStore(db)
        for s in setups.SETUPS:
            if s.name in results:
                await store.record(kind="study", name=s.name, config={"horizon": s.horizon}, execution=DEFAULT,
                                   window=(days[0].date(), days[-1].date()), fingerprint=fp, folds=[],
                                   metrics=results[s.name])
                if "similar" in results[s.name]:
                    await store.record(kind="study", name=f"similar:{s.name}", config={"horizon": s.horizon, "k": similar.K},
                                       execution=DEFAULT, window=(days[0].date(), days[-1].date()), fingerprint=fp,
                                       folds=[], metrics=results[s.name]["similar"])
    except Exception as exc:
        logger.warning("lab runs for picks not recorded: %s", exc)


LONG_SUFFIX = ":long"  # paper-only twin held 2x the horizon (RL sandbox side finding, 2026-10-19)


async def _forward(db, new: list[dict], now: datetime) -> None:
    """Two forward records per new pick, never raises: the pick at its horizon, and a
    `<setup>:long` twin held twice as long. The twin is scored only; nothing trades it."""
    try:
        from backend.forward.store import ForwardStore

        store = ForwardStore(db)
        for p in new:
            common = dict(source="picks", user_id="system", symbol=p["symbol"], side="BUY", decided_at=now,
                          intraday=False, ref_price=p["entry_ref"])
            await store.record(name=p["setup"], horizon_days=p["horizon"],
                               predicted={"p_up": p["p_up"], "median": p["expected"]["median"]}, **common)
            await store.record(name=p["setup"] + LONG_SUFFIX, horizon_days=2 * p["horizon"], **common)
    except Exception as exc:
        logger.warning("forward records for picks not written: %s", exc)


def _until(t: dict, day: date) -> dict:
    """The wide table as it stood at the close of `day`."""
    end = pd.Timestamp(day)
    return {k: v.loc[:end] for k, v in t.items()}


async def backfill(db, days: list[date], now: Optional[datetime] = None) -> int:
    """Stores the picks `compute` would have made on each past `day` (the table cut at that close, so no
    look-ahead), marked `backfilled: true` so `forward` and `live_refusal` never count them. No forward
    records; the daily `run` scores them once they mature. Returns how many were new.

        python -m backend.forecast.picks backfill 2026-10-01 2026-10-16
    """
    now = now or datetime.now(timezone.utc)
    t = await load(db, now)
    if t is None:
        return 0
    added = 0
    for day in days:
        if not is_trading_day(day):
            continue
        _, made = await asyncio.to_thread(compute, _until(t, day))
        made = [p for p in made if p["date"] == day.isoformat()]
        known = set(await db[PICKS].distinct("_id", {"_id": {"$in": [p["_id"] for p in made]}}))
        new = [{**p, "created_at": now, "outcome": None, "backfilled": True} for p in made if p["_id"] not in known]
        if new:
            await db[PICKS].insert_many(new)
        added += len(new)
        logger.info("picks backfill %s: %d new", day, len(new))
    return added


async def run(db, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    t = await load(db, now)
    if t is None:
        return {"picks": 0, "scored": 0}
    results, today = await asyncio.to_thread(compute, t)
    await _record_runs(db, t, results)
    await db[STUDY].replace_one({"_id": "latest"}, {"as_of": now, "setups": list(results.values())}, upsert=True)

    known = set(await db[PICKS].distinct("_id", {"_id": {"$in": [p["_id"] for p in today]}}))
    new = [{**p, "created_at": now, "outcome": None} for p in today if p["_id"] not in known]
    if new:
        await db[PICKS].insert_many(new)
        await _forward(db, new, now)

    scored = 0
    async for pick in db[PICKS].find({"outcome": None}):
        result = score(t, pick)
        if result:
            await db[PICKS].update_one({"_id": pick["_id"]}, {"$set": {"outcome": result, "scored_at": now}})
            scored += 1
    logger.info("picks: %d new, %d scored", len(new), scored)
    return {"picks": len(new), "scored": scored}


if __name__ == "__main__":
    import sys

    from backend.core.market_calendar import trading_days_between
    from backend.database import db as _db

    async def _main(a: str, b: str) -> None:
        await _db.connect_to_database()
        days = trading_days_between(date.fromisoformat(a), date.fromisoformat(b))
        print(f"backfilled {await backfill(_db.db, days)} pick(s) over {len(days)} trading day(s)")

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 4 or sys.argv[1] != "backfill":
        sys.exit("usage: python -m backend.forecast.picks backfill FROM TO")
    asyncio.run(_main(sys.argv[2], sys.argv[3]))
