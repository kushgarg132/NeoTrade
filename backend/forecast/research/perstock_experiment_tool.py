"""Research only (not wired anywhere): can a per-stock forecast of a pick's forward NET excess
return beat the setup's pooled base rate out of sample?

    python -m backend.forecast.research.perstock_experiment_tool DUMP.pkl

DUMP.pkl = pickle of (daily_bars DataFrame [symbol, date, ohlcv], {symbol: sector}) copied read-only
from production. Needs lightgbm + scikit-learn (install outside the app image). Events, cost and
walk-forward conventions are the Picks ones (setups.table, study.run/events, net of slipped CNC
charges, excess = net - NIFTY over the same window, one event per stock per horizon window,
yearly folds from lab.splits, min 3 train years, train = events that EXITED before the test year
minus an embargo of one horizon, so purged).

Methods per setup (each config is one (name, params)):
  bucket:<f1[+f2]>   bucket base rate if the bucket has >= 100 train events, else the pooled rate
  shrink<k>:<...>    empirical-Bayes blend (n*bucket + k*pooled)/(n+k)
  lgbm_clf / lgbm_reg / logreg   small models on ~11 features incl. sector one-hot and regime
Metrics (pooled over test years, vs the pooled train base rate): Brier skill on P(beat NIFTY),
per-year rank IC of the predicted vs realised excess (years > 0, t of the yearly mean), and the
top-half minus bottom-half realised-excess spread inside each test year.

Caveats: today's universe (survivorship bias); the sector map holds few symbols; Mongo
`fundamentals` is a current snapshot, not point-in-time, so it is NOT used.
"""

import itertools
import pickle
import sys
import time

import numpy as np
import pandas as pd

from backend.forecast import setups, similar, study
from backend.lab.splits import yearly_folds

MIN_BUCKET = 100
SHRINK_K = (100, 300)
MIN_TRAIN, MIN_TEST = 300, 20
EMBARGO_FACTOR = 1.5  # trading days -> calendar days
BUCKET_FEATS = ("regime", "sector", "vol", "d52h", "rs1m")
SINGLE = [(f,) for f in BUCKET_FEATS]
PAIRS = list(itertools.combinations(BUCKET_FEATS, 2))
MODEL_FEATS = ["vol60", "mom", "dist_high", "strength", "regime", "rel20", "rel60", "ret5", "nifty_r60", "vratio"]


def load(path: str):
    with open(path, "rb") as f:
        df, sectors = pickle.load(f)
    df["date"] = pd.to_datetime(df["date"])
    frames = {s: g.set_index("date").sort_index() for s, g in df.groupby("symbol")}
    return setups.table(frames), sectors


def event_table(t: dict, sectors: dict) -> pd.DataFrame:
    """All setups' events with signal-day features (bars <= signal day only)."""
    close, nifty, vol = t["close"], t["nifty_close"], t["volume"]
    f = similar._frames(t)
    extra = {"rel60": close.pct_change(60, fill_method=None).sub(nifty.pct_change(60, fill_method=None), axis=0),
             "ret5": close.pct_change(5, fill_method=None),
             "vratio": vol / vol.shift(1).rolling(20, min_periods=20).mean()}
    nifty_r60 = nifty.pct_change(60)
    days = close.index
    _, fires = study.run(t, setups.SETUPS)
    out = []
    for s in setups.SETUPS:
        ev = study.events(t, s, fires[s.name])
        pos = days.get_indexer(ev["signal"])
        cols = close.columns.get_indexer(ev["symbol"])
        ev = ev.assign(setup=s.name, horizon=s.horizon, strength=fires[s.name].to_numpy()[pos, cols],
                       regime=f["regime"].to_numpy()[pos], nifty_r60=nifty_r60.to_numpy()[pos])
        for name, fr in {**f, **extra}.items():
            if name != "regime":
                ev[name] = fr.to_numpy()[pos, cols]
        ev["sector"] = ev["symbol"].map(sectors).fillna("Other")
        out.append(ev)
    ev = pd.concat(out, ignore_index=True)
    ev["excess"] = ev["net"] - ev["nifty"]
    ev["y"] = (ev["excess"] > 0).astype(float)
    return ev


def labels(train: pd.DataFrame, test: pd.DataFrame, feats: tuple) -> tuple[pd.Series, pd.Series]:
    """Bucket label per row of train/test for feats; numeric ones cut at the TRAIN terciles; NaN if any is missing."""
    cols_tr, cols_te = [], []
    for ft in feats:
        if ft == "regime":
            a, b = (train["regime"] > 0), (test["regime"] > 0)
            na_tr, na_te = train["regime"].isna(), test["regime"].isna()
        elif ft == "sector":
            a, b, na_tr, na_te = train["sector"], test["sector"], train["sector"].isna(), test["sector"].isna()
        else:
            src = {"vol": "vol60", "d52h": "dist_high", "rs1m": "rel20"}[ft]
            q = train[src].quantile([1 / 3, 2 / 3]).to_numpy()
            a = pd.Series(np.searchsorted(q, train[src].to_numpy()), index=train.index)
            b = pd.Series(np.searchsorted(q, test[src].to_numpy()), index=test.index)
            na_tr, na_te = train[src].isna(), test[src].isna()
        cols_tr.append(a.astype(str).where(~na_tr))
        cols_te.append(b.astype(str).where(~na_te))
    join = lambda cols: cols[0] if len(cols) == 1 else cols[0].str.cat(cols[1:], sep="|")
    return join(cols_tr), join(cols_te)


def bucket_pred(train, test, feats, shrink_k):
    """-> (p, e) per test row: bucket rate/mean, hard fallback (shrink_k None) or EB blend."""
    p0, e0 = train["y"].mean(), train["excess"].mean()
    ltr, lte = labels(train, test, feats)
    g = train.assign(_l=ltr).dropna(subset=["_l"]).groupby("_l").agg(n=("y", "size"), p=("y", "mean"), e=("excess", "mean"))
    m = g.reindex(lte.fillna("__none__").to_numpy())
    n = m["n"].fillna(0).to_numpy()
    if shrink_k is None:
        use = n >= MIN_BUCKET
        return np.where(use, m["p"].fillna(p0), p0), np.where(use, m["e"].fillna(e0), e0)
    w = n / (n + shrink_k)
    return w * m["p"].fillna(p0).to_numpy() + (1 - w) * p0, w * m["e"].fillna(e0).to_numpy() + (1 - w) * e0


def _design(train, test, sector_levels):
    cols = MODEL_FEATS
    med = train[cols].median()
    def mk(d, fill):
        x = d[cols].copy()
        x = x.fillna(med) if fill else x
        return pd.concat([x, pd.DataFrame({f"sec_{s}": (d["sector"] == s).astype(float) for s in sector_levels}, index=d.index)], axis=1)
    return mk(train, False), mk(test, False), mk(train, True), mk(test, True)


def model_pred(train, test, kind):
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    levels = sorted(train["sector"].value_counts().loc[lambda s: s >= MIN_BUCKET].index)
    Xtr, Xte, Ftr, Fte = _design(train, test, levels)
    common = dict(n_estimators=150, learning_rate=0.03, num_leaves=4, min_child_samples=100, subsample=0.7,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=0)
    if kind == "lgbm_clf":
        p = lgb.LGBMClassifier(**common).fit(Xtr, train["y"]).predict_proba(Xte)[:, 1]
        return p, p
    if kind == "lgbm_reg":
        e = lgb.LGBMRegressor(**common).fit(Xtr, train["excess"]).predict(Xte)
        return None, e
    sc = StandardScaler().fit(Ftr)
    p = LogisticRegression(C=0.05, max_iter=500).fit(sc.transform(Ftr), train["y"]).predict_proba(sc.transform(Fte))[:, 1]
    return p, p


def configs():
    c = {}
    for feats in SINGLE + PAIRS:
        tag = "+".join(feats)
        c[f"bucket:{tag}"] = lambda tr, te, f=feats: bucket_pred(tr, te, f, None)
        for k in SHRINK_K:
            c[f"shrink{k}:{tag}"] = lambda tr, te, f=feats, k=k: bucket_pred(tr, te, f, k)
    for kind in ("lgbm_clf", "lgbm_reg", "logreg"):
        c[kind] = lambda tr, te, kind=kind: model_pred(tr, te, kind)
    return c


def spearman(a, b):
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def evaluate(ev: pd.DataFrame, cfgs: dict) -> dict:
    """setup events -> {config: metrics}. One walk-forward pass, all configs share the folds."""
    folds = yearly_folds(list(ev["signal"].dt.date), min_train_years=3)
    horizon = int(ev["horizon"].iat[0])
    acc = {k: {"p": [], "y": [], "base": [], "ic": [], "spread": [], "spread_n": 0} for k in cfgs}
    for fold in folds:
        start = pd.Timestamp(fold.test_start)
        train = ev[ev["exit"] < start - pd.Timedelta(days=int(horizon * EMBARGO_FACTOR))]  # purge + embargo
        test = ev[ev["signal"].dt.year == fold.year]
        if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
            continue
        p0, x = train["y"].mean(), test["excess"].to_numpy()
        y = test["y"].to_numpy()
        for name, fn in cfgs.items():
            p, e = fn(train, test)
            a = acc[name]
            if p is not None:
                a["p"] += list(p); a["y"] += list(y); a["base"] += [p0] * len(y)
            if np.ptp(e) > 0:
                a["ic"].append(spearman(e, x))
                r = pd.Series(e).rank(pct=True, method="average").to_numpy()
                top, bot = x[r > 0.5], x[r <= 0.5]
                if len(top) and len(bot):
                    a["spread"].append(float(top.mean() - bot.mean()))
            else:  # constant prediction: no ranking skill by construction
                a["ic"].append(0.0); a["spread"].append(0.0)
    res = {}
    for name, a in acc.items():
        ic, sp = np.array(a["ic"]), np.array(a["spread"])
        t = lambda v: float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))) if len(v) > 2 and v.std() > 0 else 0.0
        skill = None
        if a["p"]:
            y_, p_, b_ = map(np.array, (a["y"], a["p"], a["base"]))
            skill = float(1 - ((p_ - y_) ** 2).sum() / ((b_ - y_) ** 2).sum())
        res[name] = {"skill": skill, "ic_pos": int((ic > 0).sum()), "years": len(ic), "ic_mean": float(ic.mean()) if len(ic) else 0.0,
                     "ic_t": t(ic) if len(ic) else 0.0, "spread": float(sp.mean()) if len(sp) else 0.0,
                     "spread_pos": int((sp > 0).sum()), "spread_t": t(sp) if len(sp) else 0.0}
    return res


def passes(m: dict) -> bool:
    """Candidate bar for a screen (the shipping bar is stricter, see the report): Brier skill > 0, IC > 0 in >= 70% of
    years, IC t >= 2, top-half beats bottom-half in >= 70% of years."""
    return bool(m["skill"] is not None and m["skill"] > 0 and m["years"] and m["ic_pos"] / m["years"] >= 0.7
                and m["ic_t"] >= 2 and m["spread_pos"] / m["years"] >= 0.7)


def run(path: str) -> None:
    t0 = time.perf_counter()
    t, sectors = load(path)
    ev = event_table(t, sectors)
    cfgs = configs()
    print(f"events {len(ev)} {ev['setup'].value_counts().to_dict()} {ev['signal'].min().date()}..{ev['signal'].max().date()}; "
          f"symbols {t['close'].shape[1]}, mapped sectors {len(sectors)}, event rows with a real sector "
          f"{(ev['sector'] != 'Other').mean():.0%}; build {time.perf_counter() - t0:.0f}s")
    total = 0
    for s in setups.SETUPS:
        e = ev[ev["setup"] == s.name].sort_values("signal").reset_index(drop=True)
        res = evaluate(e, cfgs)
        total += len(res)
        print(f"\n=== {s.name} (h={s.horizon}) n={len(e)} base P(beat)={e['y'].mean():.3f} mean excess={e['excess'].mean():+.4f}")
        print(f"{'config':32} {'skill':>8} {'IC+/yrs':>8} {'ICmean':>7} {'ICt':>5} {'spread':>8} {'sp+/yrs':>8} {'spt':>5} pass")
        for name, m in sorted(res.items(), key=lambda kv: -(kv[1]["ic_t"])):
            if m["ic_t"] < 1.0 and not passes(m) and not name.startswith(("lgbm", "logreg")):
                continue  # print only configs with a hint of rank skill, plus the models
            sk = "   n/a" if m["skill"] is None else f"{m['skill']:+.4f}"
            print(f"{name:32} {sk:>8} {m['ic_pos']:>3}/{m['years']:<4} {m['ic_mean']:+.3f} {m['ic_t']:5.1f} "
                  f"{m['spread']:+8.4f} {m['spread_pos']:>3}/{m['years']:<4} {m['spread_t']:5.1f} {passes(m)}")
        best = max((m["skill"] for m in res.values() if m["skill"] is not None), default=None)
        print(f"   best Brier skill of {len(res)} configs: {best:+.4f}; passing screen: {[k for k, m in res.items() if passes(m)]}")
    print(f"\nconfigs per setup {len(cfgs)} ({len(SINGLE)} single x (hard + {len(SHRINK_K)} shrink) + {len(PAIRS)} pairs x same + 3 models); "
          f"total evaluated {total}; runtime {time.perf_counter() - t0:.0f}s")


def _check() -> None:
    tr = pd.DataFrame({"y": [1.0] * 150 + [0.0] * 150, "excess": [0.1] * 150 + [-0.1] * 150, "regime": [1.0] * 150 + [-1.0] * 150,
                       "sector": ["A"] * 300})
    te = pd.DataFrame({"regime": [1.0, -1.0, np.nan], "sector": ["A"] * 3})
    p, e = bucket_pred(tr, te, ("regime",), None)
    assert list(p) == [1.0, 0.0, 0.5], p  # NaN bucket falls back to pooled
    p, _ = bucket_pred(tr, te, ("regime",), 150)  # n=150 -> weight .5
    assert np.allclose(p, [0.75, 0.25, 0.5]), p


if __name__ == "__main__":
    _check()
    run(sys.argv[1])
