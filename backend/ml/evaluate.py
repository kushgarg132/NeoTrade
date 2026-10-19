"""ML ranking harness: does a LightGBM cross-sectional model beat the Picks momentum rule?

    docker exec neotrade-jobs nice python -m backend.ml.evaluate [--horizon 20]

Research only, run by hand, no schedule; nothing in the app imports it. Per horizon H the
folds are `lab.splits.yearly_folds` (3 train years min, no extra purge) and a train row
needs `label_end < test_start`, which removes every row whose label overlaps the test year. A LightGBM regressor ranks (target: excess over NIFTY) and a
classifier gives P(up). Every run is recorded in `lab_runs` (kind `ml`), passed or not.
"""

import argparse
import asyncio
import math

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.forecast import picks
from backend.lab.assumptions import DEFAULT
from backend.lab.runs import LabRunStore, fingerprint
from backend.lab.splits import yearly_folds
from backend.ml.features import FEATURES, STEP, features, long_table

HORIZONS = (20, 60)
# lightgbm's native API: the LGBM* sklearn wrappers need scikit-learn, which production does not install
PARAMS = dict(learning_rate=0.03, num_leaves=31, min_data_in_leaf=200, bagging_fraction=0.8, bagging_freq=1,
              feature_fraction=0.8, num_threads=1, verbose=-1, seed=0)
# 1 thread: 4 were ~25x slower on this shared 4-core host (OpenMP spin-waits)
ROUNDS = 300
CAVEATS = ["no point-in-time NIFTY 200 membership (survivorship +4-8%/yr)",
           "price/volume features only (no fundamentals history)"]
MIN_NAMES = 20      # a day needs this many names to have a rank IC / a top decile
MIN_IC_T = 2.0
BASELINE = "mom_vol"  # momentum_vol_60's score (12-1 month return / 60-day vol), see features.py


def _days(df: pd.DataFrame) -> pd.Series:
    return df["date"].dt.date


def split(df: pd.DataFrame, horizon: int):
    """Yield (fold, train, test): train rows ended (label_end) before the test year starts."""
    for fold in yearly_folds(sorted(set(_days(df))), min_train_years=3, purge_days=0):  # label overlap is removed by label_end below
        d = _days(df)
        train = df[(d < fold.train_end) & (df["label_end"].dt.date < fold.test_start)]
        test = df[(d >= fold.test_start) & (d < fold.test_end)]
        if len(train) and len(test):
            yield fold, train, test


def rank_ic(df: pd.DataFrame, score: str) -> pd.Series:
    """Spearman(score, excess) per date, over dates with enough names."""
    out = {d: spearmanr(g[score], g["excess"])[0] for d, g in df.groupby("date") if len(g) >= MIN_NAMES}
    return pd.Series(out, dtype=float).dropna()


def ic_t(ic: pd.Series, horizon: int = 20) -> float | None:
    """mean / standard error of block-mean ICs, blocks of consecutive sampled dates spanning the
    horizon, so no two blocks share label days (overlapping labels would inflate t). A short tail is dropped."""
    b = math.ceil(horizon / STEP)
    m = ic.groupby(np.arange(len(ic)) // b).mean()[: len(ic) // b]
    if len(m) < 2 or not m.std(ddof=1) > 0:
        return None
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def top_decile_net(df: pd.DataFrame, score: str) -> float:
    """Mean net return per pick: top tenth by `score` on each sampled day, equal weight. Every
    pick carries its own full round trip (`net`), so turnover is charged in full."""
    picks_ = [g.nlargest(max(1, len(g) // 10), score)["net"] for _, g in df.groupby("date") if len(g) >= MIN_NAMES]
    if not picks_:
        return float("nan")
    return float(pd.concat(picks_).mean())


def _fit(train: pd.DataFrame, target: str, objective: str) -> lgb.Booster:
    return lgb.train({**PARAMS, "objective": objective}, lgb.Dataset(train[FEATURES], train[target]), ROUNDS)


def evaluate_table(df: pd.DataFrame, horizon: int) -> dict:
    parts, folds = [], []
    for fold, train, test in split(df, horizon):
        reg = _fit(train, "excess", "regression")
        clf = _fit(train, "up", "binary")
        folds.append(fold)
        parts.append(test.assign(score=reg.predict(test[FEATURES]), p_up=clf.predict(test[FEATURES]),
                                 base_p=float(train["up"].mean()), year=fold.year))
    oos = pd.concat(parts) if parts else df.iloc[:0].assign(score=0.0, p_up=0.0, base_p=0.0, year=0)
    ic = rank_ic(oos, "score") if len(oos) else pd.Series(dtype=float)
    brier = float(((oos["p_up"] - oos["up"]) ** 2).mean()) if len(oos) else float("nan")
    base = float(((oos["base_p"] - oos["up"]) ** 2).mean()) if len(oos) else float("nan")
    model, momentum = (top_decile_net(oos, c) for c in ("score", BASELINE)) if len(oos) else (float("nan"),) * 2
    by_year = {int(y): float(v) for y, v in ic.groupby(ic.index.year).mean().items()} if len(ic) else {}
    for f in folds:  # a test year with no IC is a failure, not a skipped year
        by_year.setdefault(f.year, float("nan"))
    return {"ic_by_year": dict(sorted(by_year.items())),
            "ic_t": ic_t(ic, horizon) if len(ic) else None, "brier": brier, "brier_base": base,
            "brier_skill": 1 - brier / base if base else float("nan"),
            "portfolio": {"model": model, "momentum": momentum, "excess_vs_momentum": model - momentum},
            "folds": folds}


def evaluate(t: dict, horizon: int) -> dict:
    return evaluate_table(long_table(features(t), t, horizon, STEP), horizon)


def passes(result: dict) -> tuple[bool, list[str]]:
    """The bar: every test year IC > 0, ic_t > 2, beats momentum after costs, Brier skill > 0."""
    why = []
    ic = result.get("ic_by_year") or {}
    bad = sorted(y for y, v in ic.items() if not v > 0)
    if not ic:
        why.append("no test years: IC missing")
    elif bad:
        why.append(f"IC not positive in {', '.join(map(str, bad))}")
    t = result.get("ic_t")
    if t is None or not t > MIN_IC_T:
        why.append(f"IC t-stat {t if t is None else round(t, 2)} is not above {MIN_IC_T}")
    if not result["portfolio"]["excess_vs_momentum"] > 0:
        why.append(f"top decile net {result['portfolio']['excess_vs_momentum']:+.4f} vs momentum, not above 0")
    if not result["brier_skill"] > 0:
        why.append(f"Brier skill {result['brier_skill']:+.4f} is not above 0")
    return not why, why


def _metrics(result: dict, ok: bool, why: list[str]) -> dict:
    out = {k: v for k, v in result.items() if k != "folds"}
    out["ic_by_year"] = {str(y): v for y, v in out["ic_by_year"].items()}  # Mongo keys are strings
    return {**out, "passed": ok, "reasons": why, "caveats": CAVEATS}


async def run(db, now, horizons=HORIZONS) -> dict[int, dict]:
    """Evaluate every horizon on the stored bars and record one `lab_runs` row each."""
    t = await picks.load(db, now)
    if t is None:
        return {}
    store, out = LabRunStore(db), {}
    window = (t["close"].index[0].date(), t["close"].index[-1].date())
    fp = await asyncio.to_thread(fingerprint, t["close"])
    for h in horizons:
        result = await asyncio.to_thread(evaluate, t, h)
        ok, why = passes(result)
        run_id = await store.record(kind="ml", name=f"lgbm_h{h}", execution=DEFAULT, window=window, fingerprint=fp,
                           config={"params": {**PARAMS, "rounds": ROUNDS}, "features": FEATURES, "horizon": h, "step": STEP},
                           folds=result["folds"], metrics=_metrics(result, ok, why))
        out[h] = {**result, "passed": ok, "reasons": why, "run_id": run_id}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.ml.evaluate")
    parser.add_argument("--horizon", type=int, choices=HORIZONS)
    args = parser.parse_args(argv)

    async def go():
        from datetime import datetime, timezone
        from backend.database import db
        await db.connect_to_database()
        return await run(db.db, datetime.now(timezone.utc), (args.horizon,) if args.horizon else HORIZONS)

    results = asyncio.run(go())
    if not results:
        print("no bars")
        return 1
    for h, r in results.items():
        print(f"H={h}: {'PASS' if r['passed'] else 'FAIL'}  ic_t {r['ic_t']}  brier_skill {r['brier_skill']:+.4f}  "
              f"excess_vs_momentum {r['portfolio']['excess_vs_momentum']:+.4f}")
        print(f"  recorded {r['run_id']}" if r["run_id"] else "  NOT RECORDED")
        print("  IC by year: " + ", ".join(f"{y} {v:+.3f}" for y, v in r["ic_by_year"].items()))
        for why in r["reasons"]:
            print("  - " + why)
    return 0 if all(r["run_id"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
