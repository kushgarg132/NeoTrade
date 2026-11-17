"""python -m backend.forecast.variants [--json PATH]

Tests the `forecast/conditions.py` analyses on the stored bars with the Picks study itself
(net of charges at study.NOTIONAL, out of sample, over the average stock of the same month):

- gated: each base setup firing only with breadth >= 50%, India VIX <= its trailing-year 80th
  percentile, or the weekly trend up;
- timed: the monthly setups entered on a candle-pattern break instead of on the month's first day;
- standalone: each candle pattern as its own setup (the control);
- similar: the per-stock forecast's skill with breadth / VIX / weekly trend added to its features.

Every variant counts as a trial: the bar is study.min_t over the base setups plus all variants
(Bonferroni), so trying more ideas makes each one harder to pass. A variant belongs in
`setups.SETUPS` only when it clears that bar and beats its base.
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone

from backend.forecast import conditions as c
from backend.forecast import setups, similar, study

GATED_BASES = ("rs_leaders_regime", "momentum_vol_60", "breakout", "results_drift")
TIMED_BASES = ("rs_leaders_regime", "momentum_vol_60")
GATES = (
    ("breadth", "breadth >= 50%", c.breadth_ok, "at least half the index above its 200-day average"),
    ("vix", "VIX calm", c.vix_ok, "India VIX at or below its trailing-year 80th percentile"),
    ("weekly", "weekly trend up", c.weekly_up, "last completed week closed above its 30-week average"),
)
TRIGGERS = ("inside_bar", "nr7", "bullish_engulfing", "hammer")


def build() -> list:
    by = setups.BY_NAME
    out = []
    for base in GATED_BASES:
        for key, short, cond, text in GATES:
            out.append(c.gated(by[base], f"{base}+{key}", f"{by[base].label} ({short})", cond, text))
    for base in TIMED_BASES:
        for name in TRIGGERS:
            label = name.replace("_", " ")
            out.append(c.timed(by[base], f"{base}@{name}", f"{by[base].label} (on {label} break)",
                               c.PATTERNS[name], label))
    out += [c.standalone(name, fn) for name, fn in c.PATTERNS.items()]
    return out


VARIANTS = build()


def _base_of(name: str) -> str | None:
    for sep in ("+", "@"):
        if sep in name:
            return name.split(sep, 1)[0]
    return None


def _row(r: dict, base: dict | None) -> dict:
    adj = r["adjusted"]
    row = {"name": r["setup"], "n": r["n"], "excess": adj["excess"], "t": adj["t"], "halves": adj["halves"],
           "edge": adj["edge"], "beat_average": r["basket"]["beat_average"]}
    if base is not None and adj["excess"] is not None and base["adjusted"]["excess"] is not None:
        row["vs_base"] = adj["excess"] - base["adjusted"]["excess"]
        row["better"] = bool(adj["edge"] and row["vs_base"] > 0)
    return row


def similar_check(t: dict, results: dict, fires: dict) -> list[dict]:
    """Per base setup: the similar forecast's skill with the current features and with each extra added."""
    rows = []
    for s in setups.SETUPS:
        if results[s.name]["n"] < study.MIN_N:
            continue
        ev = study.events(t, s, fires[s.name])
        row = {"setup": s.name}
        for label, feats in [("current", similar.FEATURES), *((f"+{x}", (*similar.FEATURES, x)) for x in similar.EXTRA),
                             ("+all", (*similar.FEATURES, *similar.EXTRA))]:
            v = similar.validate(similar.event_features(t, ev, fires[s.name], feats), feats)
            row[label] = {"skill": v["skill"], "ic_years": v["ic_years"], "personalised": v["personalised"]}
        rows.append(row)
    return rows


def compare(t: dict) -> dict:
    trials = (*setups.SETUPS, *VARIANTS)
    results, fires = study.run(t, trials)
    rows = [_row(results[v.name], results.get(_base_of(v.name))) for v in trials]
    return {"trials": len(trials), "need_t": study.min_t(len(trials)), "rows": rows,
            "similar": similar_check(t, results, fires)}


def _fmt(x, pct=False):
    if x is None:
        return "-"
    return f"{x:+.2%}" if pct else f"{x:.2f}"


async def _main(path: str | None) -> None:
    from backend.database import db
    from backend.forecast import picks

    await db.connect_to_database()
    t = await picks.load(db.db, datetime.now(timezone.utc))
    if t is None:
        raise SystemExit("no bars")
    out = await asyncio.to_thread(compare, t)
    print(f"{out['trials']} trials, need t >= {out['need_t']:.2f}; VIX bars: {'vix' in t}")
    print(f"{'setup':44} {'n':>5} {'excess':>8} {'t':>6} {'vs base':>8} {'beat avg':>8}  halves")
    for r in out["rows"]:
        halves = " / ".join(_fmt(h, True) for h in (r["halves"] or []))
        print(f"{r['name']:44} {r['n']:>5} {_fmt(r['excess'], True):>8} {_fmt(r['t']):>6} "
              f"{_fmt(r.get('vs_base'), True):>8} {_fmt(r['beat_average']):>8}  {halves}"
              f"{'  EDGE' if r['edge'] else ''}{'  BETTER' if r.get('better') else ''}")
    print("\nsimilar forecast skill (Brier skill vs base rate; IC>0 years):")
    for r in out["similar"]:
        print(f"  {r['setup']:22} " + "  ".join(
            f"{k} {_fmt(v['skill'])} ({v['ic_years']['positive']}/{v['ic_years']['tested']})"
            for k, v in r.items() if k != "setup"))
    if path:
        with open(path, "w") as f:
            json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json")
    asyncio.run(_main(parser.parse_args().json))
