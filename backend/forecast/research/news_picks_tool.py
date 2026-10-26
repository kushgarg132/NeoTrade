"""Research only (not wired anywhere): news plan N2.1, N2.2 and N2.5. Does news improve Picks?

    python -m backend.forecast.research.news_picks_tool

Reads production read-only: daily bars (as `picks.load`) and the N0.5 backfill (`news_history`, scored by
`datalayer/backfill_news.py`). Every live setup's own events (`study.events`: signal on close t, entry t+1
open, exit close t+1+H, net of costs, NIFTY over the same window) are kept to the window the news history
covers. Every rule below was fixed before the full history was scored.

N2.1 veto. Events split two ways:
    news veto     a scored item on the stock with direction <= -BAD_DIRECTION and impact >= BAD_IMPACT,
                  published in the BAD_DAYS calendar days up to and including the signal day
    results veto  an NSE results filing on the stock after the signal and up to the exit
  Yardstick: `study.adjusted_edge` (OOS excess over NIFTY minus the month's all-stocks baseline,
  month-block bootstrap t) on kept vs all events. Passes when kept excess > all excess, kept t >= all t,
  and at least MIN_VETOED events were vetoed (else "too few").

N2.2 sector tilt. Each event's sector sentiment: the impact-weighted mean direction of sector-scope impacts
  on its stock's NSE industry over TILT_DAYS calendar days up to the signal. Per signal month (>= MIN_MONTH
  events with a reading), the rank correlation (IC) of that sentiment with excess over NIFTY. Passes when
  the yearly mean IC is > 0 in >= TILT_YEARS of test years (years with a month).

N2.5 regime. Each basket month (study.basket's: the setup's picks of one signal month, >= study.BASKET_MIN)
  gets the market's news regime: impact-weighted mean direction of market-scope impacts over REGIME_DAYS up
  to the month's first signal; risk-off below -REGIME_CUT, risk-on above +REGIME_CUT, else neutral. Passes
  (a smaller risk-off basket would help) when there are >= MIN_RISK_OFF risk-off months, their mean
  baseline-adjusted basket excess is < 0, and it is below the other months' mean.

Caveats: the history is ~2 years (few test months, so every t and IC is weak), Google items carry a day
not a time, and the backfill scorer post-dates the history (it may know what followed: a filter that
"works" may be hindsight). A pass is a reason for a forward test, not proof.
"""

import asyncio
import bisect
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backend.forecast import setups, study

BAD_DIRECTION, BAD_IMPACT, BAD_DAYS = 0.5, 7, 3
MIN_VETOED = 20
RESULTS = re.compile(r"financial results", re.I)
TILT_DAYS, MIN_MONTH, TILT_YEARS = 5, 5, 0.7
REGIME_DAYS, REGIME_CUT, MIN_RISK_OFF = 5, 0.2, 3
MARKET = "INDIA"


def _day(at: datetime) -> pd.Timestamp:
    from backend.datalayer.backfill_news import _day as ist_day

    return pd.Timestamp(ist_day(at))


def flags(items: list[dict]) -> tuple[dict[str, list], dict[str, list]]:
    """news_history docs -> (symbol -> sorted bad-news days, symbol -> sorted results days), IST dates as Timestamps."""
    bad, results = {}, {}
    for doc in items:
        day = _day(doc["published_at"])
        for i in doc.get("impacts") or []:
            if i["type"] == "symbol" and i["direction"] <= -BAD_DIRECTION and i["impact"] >= BAD_IMPACT:
                bad.setdefault(i["target"], []).append(day)
        if "nse" in (doc.get("feeds") or []) and RESULTS.search(doc.get("title", "")):
            for s in doc.get("symbols") or []:
                results.setdefault(s, []).append(day)
    return ({s: sorted(d) for s, d in bad.items()}, {s: sorted(d) for s, d in results.items()})


def tag(ev: pd.DataFrame, bad: dict, results: dict) -> pd.DataFrame:
    """Adds bool columns `bad_news` and `results` to study events."""
    def any_in(days, lo, hi):
        return any(lo < d <= hi for d in days)

    ev = ev.copy()
    ev["bad_news"] = [any_in(bad.get(s, ()), sig - timedelta(days=BAD_DAYS), sig)
                      for s, sig in zip(ev["symbol"], ev["signal"])]
    ev["results"] = [any_in(results.get(s, ()), sig, ex) for s, sig, ex in zip(ev["symbol"], ev["signal"], ev["exit"])]
    return ev


def verdict(ev: pd.DataFrame, column: str, baseline: pd.Series, wf: dict) -> dict:
    """adjusted_edge on all / kept / vetoed events; `passes` per the N2.1 rule."""
    vetoed = ev[ev[column]]
    out = {"all": study.adjusted_edge(ev, baseline, wf), "kept": study.adjusted_edge(ev[~ev[column]], baseline, wf),
           "vetoed": study.adjusted_edge(vetoed, baseline, wf), "n_vetoed": int(len(vetoed))}
    a, k = out["all"], out["kept"]
    if len(vetoed) < MIN_VETOED or a["excess"] is None or k["excess"] is None:
        out["passes"] = None
    else:
        out["passes"] = bool(k["excess"] > a["excess"] and (k["t"] or 0) >= (a["t"] or 0))
    return out


# ------------------------------------------------------------------ N2.2 / N2.5


def impacts_by_target(items: list[dict], kind: str) -> dict[str, tuple[list, list, list]]:
    """target -> (sorted days, directions, impacts) of `kind` ("sector"/"market") impacts."""
    points = {}
    for doc in items:
        day = _day(doc["published_at"])
        for i in doc.get("impacts") or []:
            if i["type"] == kind:
                points.setdefault(i["target"], []).append((day, i["direction"], i["impact"]))
    out = {}
    for target, rows in points.items():
        rows.sort(key=lambda r: r[0])
        out[target] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
    return out


def window_mean(series, day: pd.Timestamp, days: int):
    """Impact-weighted mean direction over (day - days, day], or None without a reading."""
    if not series:
        return None
    dates, directions, impacts = series
    lo, hi = bisect.bisect_right(dates, day - timedelta(days=days)), bisect.bisect_right(dates, day)
    w = sum(impacts[lo:hi])
    return sum(d * i for d, i in zip(directions[lo:hi], impacts[lo:hi])) / w if w else None


def tilt(ev: pd.DataFrame, sectors: dict, sector_of: dict[str, str], years: list[int]) -> dict:
    """N2.2 on one setup's events: monthly IC of sector sentiment vs excess, yearly means, verdict."""
    ev = ev.assign(sent=[window_mean(sectors.get(sector_of.get(s)), sig, TILT_DAYS)
                         for s, sig in zip(ev["symbol"], ev["signal"])], ex=ev["net"] - ev["nifty"])
    ev = ev[ev["sent"].notna() & ev["signal"].dt.year.isin(years)]
    ics = []
    for month, g in ev.groupby(ev["signal"].dt.to_period("M")):
        if len(g) >= MIN_MONTH and g["sent"].nunique() > 1 and g["ex"].nunique() > 1:
            ics.append((month.year, float(g["sent"].rank().corr(g["ex"].rank()))))
    if not ics:
        return {"months": 0, "mean_ic": None, "years_positive": None, "passes": None}
    by_year = pd.DataFrame(ics, columns=["y", "ic"]).groupby("y")["ic"].mean()
    share = float((by_year > 0).mean())
    return {"months": len(ics), "mean_ic": float(np.mean([ic for _, ic in ics])), "years": len(by_year),
            "years_positive": share, "passes": share >= TILT_YEARS}


def regime(ev: pd.DataFrame, market, baseline: pd.Series, years: list[int]) -> dict:
    """N2.5 on one setup's events: basket months by market news regime, verdict."""
    ev = ev[ev["signal"].dt.year.isin(years)]
    rows = []
    for month, g in ev.groupby(ev["signal"].dt.to_period("M")):
        if len(g) < study.BASKET_MIN:
            continue
        read = window_mean(market, g["signal"].min(), REGIME_DAYS)
        bucket = "unknown" if read is None else "risk_off" if read < -REGIME_CUT else "risk_on" if read > REGIME_CUT else "neutral"
        ex = float((g["net"] - g["nifty"]).mean())
        rows.append((bucket, ex, ex - float(baseline.get(month, baseline.mean()))))
    frame = pd.DataFrame(rows, columns=["bucket", "ex", "adj"])
    buckets = {b: {"months": int(len(f)), "mean_ex": float(f["ex"].mean()), "mean_adj": float(f["adj"].mean())}
               for b, f in frame.groupby("bucket")} if len(frame) else {}
    off, rest = frame[frame["bucket"] == "risk_off"], frame[~frame["bucket"].isin(["risk_off", "unknown"])]
    passes = None
    if len(off) >= MIN_RISK_OFF and len(rest):
        passes = bool(off["adj"].mean() < 0 and off["adj"].mean() < rest["adj"].mean())
    return {"buckets": buckets, "passes": passes}


# ----------------------------------------------------------------------- run


def run(t: dict, items: list[dict], start: pd.Timestamp, end: pd.Timestamp, sector_of: dict[str, str]) -> dict:
    bad, results = flags(items)
    sectors, market = impacts_by_target(items, "sector"), impacts_by_target(items, "market").get(MARKET)
    out, base = {}, {}
    for s in setups.SETUPS:
        ev = study.events(t, s, s.signals(t))
        wf = study.walk_forward(ev)  # test years from the whole history, as the live study
        years = [y["year"] for y in wf["years"]]
        if s.horizon not in base:
            base[s.horizon] = study.baseline_by_month(t, s.horizon)
        # Only signals the news history fully covers (its look-back and the results window).
        ev = tag(ev[(ev["signal"] >= start + timedelta(days=max(BAD_DAYS, TILT_DAYS, REGIME_DAYS))) & (ev["exit"] <= end)],
                 bad, results)
        out[s.name] = {"n": int(len(ev)), **{c: verdict(ev, c, base[s.horizon], wf) for c in ("bad_news", "results")},
                       "tilt": tilt(ev, sectors, sector_of, years), "regime": regime(ev, market, base[s.horizon], years)}
    return out


def _fmt(e: dict) -> str:
    if e["excess"] is None:
        return "n/a"
    return f"{e['excess']:+.2%} t {e['t']:.1f} (n {e['oos_n']})" if e["t"] is not None else f"{e['excess']:+.2%} (n {e['oos_n']})"


_WORD = {True: "PASSES", False: "fails", None: "too little data"}


def summary(res: dict) -> str:
    lines = []
    for name, r in res.items():
        lines.append(f"{name}: {r['n']} event(s) in the news window")
        for c in ("bad_news", "results"):
            v = r[c]
            lines.append(f"  N2.1 {c:8} vetoed {v['n_vetoed']:>4}  all {_fmt(v['all'])}  kept {_fmt(v['kept'])}  "
                         f"vetoed {_fmt(v['vetoed'])}  -> {_WORD[v['passes']]}")
        tl = r["tilt"]
        ic = "n/a" if tl["mean_ic"] is None else f"{tl['mean_ic']:+.3f}"
        yp = "n/a" if tl["years_positive"] is None else f"{tl['years_positive']:.0%} of {tl['years']} yr"
        lines.append(f"  N2.2 sector tilt  months {tl['months']}  mean IC {ic}  IC>0 in {yp}  -> {_WORD[tl['passes']]}")
        rg = r["regime"]
        parts = "  ".join(f"{b} {v['months']}m adj {v['mean_adj']:+.2%}" for b, v in sorted(rg["buckets"].items()))
        lines.append(f"  N2.5 regime  {parts or 'no basket months'}  -> {_WORD[rg['passes']]}")
    return "\n".join(lines)


if __name__ == "__main__":
    from backend.database import db as _db
    from backend.datalayer.backfill_news import ITEMS
    from backend.datalayer.news import SCORED
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.forecast import picks

    async def _main() -> None:
        await _db.connect_to_database()
        db = _db.db
        t = await picks.load(db, datetime.now(timezone.utc))
        fields = {"published_at": 1, "impacts": 1, "feeds": 1, "title": 1, "symbols": 1}
        items = await db[ITEMS].find({"$or": [{"status": SCORED}, {"feeds": "nse"}]}, fields).to_list(length=None)
        if not items or t is None:
            raise SystemExit("no news history or no bars")
        days = [_day(d["published_at"]) for d in items]
        print(f"{len(items)} news item(s), {min(days).date()} .. {max(days).date()}")
        print(summary(run(t, items, min(days), max(days), nifty200_sectors())))

    asyncio.run(_main())
