"""RL exit sandbox: does a fitted-Q exit policy beat the fixed exit on Picks, out of sample?

    docker exec neotrade-jobs nice python -m backend.rl.evaluate

Research only, run by hand, no schedule; nothing in the app imports it. Per setup the folds are
`lab.splits.yearly_folds` (3 train years min) and a train episode needs `episode_end < test_start`.
In each fold the policy is fitted on train episodes only and three exit rules are applied to the
test year's episodes: `policy`, `fixed` (decide at the setup's horizon day) and `best_fixed` (the
holding day with the best mean reward on the TRAIN episodes). The baseline is whichever of the two
fixed rules did better on train, chosen per fold from train data only. Every rule decides at a close and fills at the next open. Every run is recorded in
`lab_runs` (kind `rl`), passed or not.
"""

import argparse
import asyncio
import math

import numpy as np
import pandas as pd

from backend.forecast import picks
from backend.forecast.setups import SETUPS
from backend.lab.assumptions import DEFAULT
from backend.lab.runs import LabRunStore, fingerprint
from backend.lab.splits import yearly_folds
from backend.rl import agent
from backend.rl.env import STATE, episodes, hmax, subset

ITERATIONS = 5
MIN_TRAIN_YEARS = 3
MIN_T = 2.0
MIN_HIT = 0.70
MIN_TEST_YEARS = 8
MIN_SETUPS_PASSED = 2  # family rule: one pass among five setups is not evidence
CAVEATS = ["no point-in-time NIFTY 200 membership (survivorship +4-8%/yr)", "price-only state",
           "episodes with a missing bar are dropped (conditions on halts/delistings, as study.outcome)"]


def _taken(rows: pd.DataFrame, days: pd.Series) -> pd.DataFrame:
    """One row per episode: the reward and date of the day it exits (`days`: episode -> day)."""
    want = days.rename("day").rename_axis("episode").reset_index()
    return want.merge(rows[["episode", "day", "exit_reward", "date"]], on=["episode", "day"], how="inner")


def _max_drawdown(taken: pd.DataFrame) -> float:
    """Deepest fall of the running sum of per-pick excess, picks in the order their exits happen."""
    cum = taken.sort_values(["date", "episode"], kind="mergesort")["exit_reward"].cumsum().to_numpy()
    return float((np.maximum.accumulate(np.r_[0.0, cum])[1:] - cum).max()) if len(cum) else 0.0


def _summary(taken: pd.DataFrame) -> dict:
    return {"mean_excess": float(taken["exit_reward"].mean()), "max_drawdown": _max_drawdown(taken),
            "mean_days": float(taken["day"].mean())}


def _t(x: list[float]) -> float | None:
    if len(x) < 2 or not np.std(x, ddof=1) > 0:
        return None
    return float(np.mean(x) / (np.std(x, ddof=1) / math.sqrt(len(x))))


def _empty() -> dict:
    nan = {"mean_excess": float("nan"), "max_drawdown": float("nan"), "mean_days": float("nan")}
    return {"rules": {"policy": nan, "fixed": nan, "best_fixed": nan}, "baseline": {**nan, "choice": {}},
            "improvement_by_year": {}, "mean_improvement": float("nan"), "t": None, "hit_years": float("nan"),
            "folds": []}


def evaluate_rows(rows: pd.DataFrame, setup, fit=agent.fit) -> dict:
    if rows.empty:
        return _empty()
    ep = rows.drop_duplicates("episode").set_index("episode")
    folds = yearly_folds(sorted({d.date() for d in ep["signal_date"]}), MIN_TRAIN_YEARS)
    parts = {"policy": [], "fixed": [], "best_fixed": [], "baseline": []}
    by_year, choice, used = {}, {}, []
    for fold in folds:
        start = pd.Timestamp(fold.test_start)
        train_ids = ep.index[(ep["signal_date"] < start) & (ep["episode_end"] < start)]
        test_ids = ep.index[ep["signal_date"].dt.year == fold.year]
        if not len(train_ids) or not len(test_ids):
            continue
        train, test = subset(rows, rows["episode"].isin(train_ids)), subset(rows, rows["episode"].isin(test_ids))
        policy = fit(train, ITERATIONS)
        mean_by_day = train.groupby("day")["exit_reward"].mean()  # train only: the baseline never sees the test year
        best = int(mean_by_day.idxmax())
        pick = "best_fixed" if mean_by_day[best] > mean_by_day.get(setup.horizon, -np.inf) else "fixed"
        ids = test["episode"].unique()
        taken = {"policy": _taken(test, policy.exit_days(test)),
                 "fixed": _taken(test, pd.Series(setup.horizon, index=ids)),
                 "best_fixed": _taken(test, pd.Series(best, index=ids))}
        taken["baseline"] = taken[pick]
        for k, v in taken.items():
            parts[k].append(v)
        by_year[str(fold.year)] = float(taken["policy"]["exit_reward"].mean() - taken["baseline"]["exit_reward"].mean())
        choice[str(fold.year)] = pick
        used.append(fold)
    if not used:
        return _empty()
    pooled = {k: pd.concat(v) for k, v in parts.items()}
    imp = list(by_year.values())
    return {"rules": {k: _summary(pooled[k]) for k in ("policy", "fixed", "best_fixed")},
            "baseline": {**_summary(pooled["baseline"]), "choice": choice},
            "improvement_by_year": by_year, "mean_improvement": float(np.mean(imp)), "t": _t(imp),
            "hit_years": float(np.mean([v > 0 for v in imp])), "folds": used}


def evaluate(t: dict, setup) -> dict:
    return evaluate_rows(episodes(t, setup), setup)


def passes(result: dict) -> tuple[bool, list[str]]:
    """The bar: mean yearly improvement over the baseline > 0, t >= 2, positive in >= 70% of years,
    and the policy's max drawdown no deeper than the baseline's, over at least MIN_TEST_YEARS test years.
    Reading the family of setups is `run`'s `family_passed`."""
    why = []
    if not result["improvement_by_year"]:
        return False, ["no test years"]
    if len(result["improvement_by_year"]) < MIN_TEST_YEARS:
        why.append(f"only {len(result['improvement_by_year'])} test years (< {MIN_TEST_YEARS})")
    if not result["mean_improvement"] > 0:
        why.append(f"mean improvement {result['mean_improvement']:+.4f} is not above 0")
    t = result["t"]
    if t is None or not t >= MIN_T:
        why.append(f"t-stat {t if t is None else round(t, 2)} is below {MIN_T}")
    if not result["hit_years"] >= MIN_HIT:
        why.append(f"improvement positive in {result['hit_years']:.0%} of years, below {MIN_HIT:.0%}")
    if not result["rules"]["policy"]["max_drawdown"] <= result["baseline"]["max_drawdown"]:
        why.append(f"policy max drawdown {result['rules']['policy']['max_drawdown']:.4f} is deeper than the "
                   f"baseline's {result['baseline']['max_drawdown']:.4f}")
    return not why, why


def _metrics(result: dict, ok: bool, why: list[str], setups_passed: int = 0) -> dict:
    out = {k: v for k, v in result.items() if k != "folds"}
    return {**out, "passed": ok, "reasons": why, "caveats": CAVEATS, "setups_passed": setups_passed,
            "family_passed": setups_passed >= MIN_SETUPS_PASSED}


async def run(db, now, setups=SETUPS) -> dict[str, dict]:
    """Evaluate every setup on the stored bars and record one `lab_runs` row each."""
    t = await picks.load(db, now)
    if t is None:
        return {}
    store, out = LabRunStore(db), {}
    window = (t["close"].index[0].date(), t["close"].index[-1].date())
    fp = await asyncio.to_thread(fingerprint, t["close"])
    results = {s.name: await asyncio.to_thread(evaluate, t, s) for s in setups}
    verdicts = {name: passes(r) for name, r in results.items()}
    n_passed = sum(ok for ok, _ in verdicts.values())
    for s in setups:
        result, (ok, why) = results[s.name], verdicts[s.name]
        run_id = await store.record(
            kind="rl", name=f"fqi_exit:{s.name}", execution=DEFAULT, window=window, fingerprint=fp,
            config={"params": {**agent.PARAMS, "rounds": agent.ROUNDS}, "iterations": ITERATIONS,
                    "hmax": "2 * setup.horizon", "horizon": s.horizon, "hmax_days": hmax(s), "features": STATE},
            folds=result["folds"], metrics=_metrics(result, ok, why, n_passed))
        out[s.name] = {**result, "passed": ok, "reasons": why, "run_id": run_id, "setups_passed": n_passed,
                       "family_passed": n_passed >= MIN_SETUPS_PASSED}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.rl.evaluate")
    parser.add_argument("--setup", choices=[s.name for s in SETUPS])
    args = parser.parse_args(argv)

    async def go():
        from datetime import datetime, timezone
        from backend.database import db
        await db.connect_to_database()
        chosen = tuple(s for s in SETUPS if args.setup in (None, s.name))
        return await run(db.db, datetime.now(timezone.utc), chosen)

    results = asyncio.run(go())
    if not results:
        print("no bars")
        return 1
    for name, r in results.items():
        rules = r["rules"]
        print(f"{name}: {'PASS' if r['passed'] else 'FAIL'}  mean_improvement {r['mean_improvement']:+.4f}  "
              f"t {r['t']}  hit_years {r['hit_years']:.2f}")
        print("  " + "  ".join(f"{k} {v['mean_excess']:+.4f} (dd {v['max_drawdown']:.3f}, {v['mean_days']:.1f}d)"
                               for k, v in rules.items()))
        print(f"  recorded {r['run_id']}" if r["run_id"] else "  NOT RECORDED")
        print("  by year: " + ", ".join(f"{y} {v:+.4f}" for y, v in r["improvement_by_year"].items()))
        for why in r["reasons"]:
            print("  - " + why)
    first = next(iter(results.values()))
    print(f"family: {'PASS' if first['family_passed'] else 'FAIL'} ({first['setups_passed']} setups passed, "
          f"{MIN_SETUPS_PASSED} needed)")
    return 0 if all(r["run_id"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
