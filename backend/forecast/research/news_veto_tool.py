"""Research only (not wired anywhere): N2.1 of the news plan. Does a news veto improve Picks?

    python -m backend.forecast.research.news_veto_tool

Reads production read-only: daily bars (as `picks.load`) and the N0.5 backfill (`news_history`, scored by
`datalayer/backfill_news.py`). For every live setup, the study's own events (`study.events`: signal on close
t, entry t+1 open, exit close t+1+H, net of costs, NIFTY over the same window), kept to the window the news
history covers, are split two ways:

    news veto     a scored item on the stock with direction <= -BAD_DIRECTION and impact >= BAD_IMPACT,
                  published in the BAD_DAYS calendar days up to and including the signal day
    results veto  an NSE results filing on the stock after the signal and up to the exit

Yardstick (the plan's): `study.adjusted_edge` (OOS excess over NIFTY minus the month's all-stocks
baseline, month-block bootstrap t) on the kept events vs all events. A veto passes for a setup when kept
excess > all excess, kept t >= all t, and at least MIN_VETOED events were vetoed (else "too few").
Caveats: the history is ~2 years (few test months, so t is weak), Google items carry a day not a time,
and the backfill scorer post-dates the history (it may know what followed: a veto that "works" may be
hindsight). Treat a pass as a reason for a forward test, not as proof.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.forecast import setups, study

BAD_DIRECTION, BAD_IMPACT, BAD_DAYS = 0.5, 7, 3
MIN_VETOED = 20
RESULTS = re.compile(r"financial results", re.I)


def flags(items: list[dict]) -> tuple[dict[str, list], dict[str, list]]:
    """news_history docs -> (symbol -> sorted bad-news days, symbol -> sorted results days), IST dates as Timestamps."""
    from backend.datalayer.backfill_news import _day

    bad, results = {}, {}
    for doc in items:
        day = pd.Timestamp(_day(doc["published_at"]))
        for i in doc.get("impacts") or []:
            if i["type"] == "symbol" and i["direction"] <= -BAD_DIRECTION and i["impact"] >= BAD_IMPACT:
                bad.setdefault(i["target"], []).append(day)
        if "nse" in (doc.get("feeds") or []) and RESULTS.search(doc.get("title", "")):
            for s in doc.get("symbols") or []:
                results.setdefault(s, []).append(day)
    return ({s: sorted(d) for s, d in bad.items()}, {s: sorted(d) for s, d in results.items()})


def tag(ev: pd.DataFrame, bad: dict, results: dict) -> pd.DataFrame:
    """Adds bool columns `bad_news` and `results` to study events."""
    def any_in(days, lo, hi, closed_lo):
        return any((lo <= d if closed_lo else lo < d) and d <= hi for d in days)

    ev = ev.copy()
    ev["bad_news"] = [any_in(bad.get(s, ()), sig - timedelta(days=BAD_DAYS), sig, False)
                      for s, sig in zip(ev["symbol"], ev["signal"])]
    ev["results"] = [any_in(results.get(s, ()), sig, ex, False)
                     for s, sig, ex in zip(ev["symbol"], ev["signal"], ev["exit"])]
    return ev


def verdict(ev: pd.DataFrame, column: str, baseline: pd.Series, wf: dict) -> dict:
    """adjusted_edge on all / kept / vetoed events; `passes` per the module rule."""
    vetoed = ev[ev[column]]
    out = {"all": study.adjusted_edge(ev, baseline, wf), "kept": study.adjusted_edge(ev[~ev[column]], baseline, wf),
           "vetoed": study.adjusted_edge(vetoed, baseline, wf), "n_vetoed": int(len(vetoed))}
    a, k = out["all"], out["kept"]
    if len(vetoed) < MIN_VETOED or a["excess"] is None or k["excess"] is None:
        out["passes"] = None
    else:
        out["passes"] = bool(k["excess"] > a["excess"] and (k["t"] or 0) >= (a["t"] or 0))
    return out


def run(t: dict, items: list[dict], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    bad, results = flags(items)
    out, base = {}, {}
    for s in setups.SETUPS:
        ev = study.events(t, s, s.signals(t))
        wf = study.walk_forward(ev)  # test years from the whole history, as the live study
        if s.horizon not in base:
            base[s.horizon] = study.baseline_by_month(t, s.horizon)
        # Only signals the news history fully covers (its BAD_DAYS look-back and the results window).
        ev = tag(ev[(ev["signal"] >= start + timedelta(days=BAD_DAYS)) & (ev["exit"] <= end)], bad, results)
        out[s.name] = {"n": int(len(ev)), **{c: verdict(ev, c, base[s.horizon], wf) for c in ("bad_news", "results")}}
    return out


def _fmt(e: dict) -> str:
    if e["excess"] is None:
        return "n/a"
    return f"{e['excess']:+.2%} t {e['t']:.1f} (n {e['oos_n']})" if e["t"] is not None else f"{e['excess']:+.2%} (n {e['oos_n']})"


def summary(res: dict) -> str:
    lines = []
    for name, r in res.items():
        lines.append(f"{name}: {r['n']} event(s) in the news window")
        for c in ("bad_news", "results"):
            v = r[c]
            word = {True: "PASSES", False: "fails", None: "too few vetoed"}[v["passes"]]
            lines.append(f"  {c:8} vetoed {v['n_vetoed']:>4}  all {_fmt(v['all'])}  kept {_fmt(v['kept'])}  "
                         f"vetoed {_fmt(v['vetoed'])}  -> {word}")
    return "\n".join(lines)


if __name__ == "__main__":
    from backend.database import db as _db
    from backend.datalayer.backfill_news import ITEMS
    from backend.datalayer.news import SCORED
    from backend.forecast import picks

    async def _main() -> None:
        await _db.connect_to_database()
        db = _db.db
        t = await picks.load(db, datetime.now(timezone.utc))
        fields = {"published_at": 1, "impacts": 1, "feeds": 1, "title": 1, "symbols": 1}
        items = await db[ITEMS].find({"$or": [{"status": SCORED}, {"feeds": "nse"}]}, fields).to_list(length=None)
        if not items or t is None:
            raise SystemExit("no news history or no bars")
        days = [pd.Timestamp(d["published_at"].date()) for d in items]
        print(f"{len(items)} news item(s), {min(days).date()} .. {max(days).date()}")
        print(summary(run(t, items, min(days), max(days))))

    asyncio.run(_main())
