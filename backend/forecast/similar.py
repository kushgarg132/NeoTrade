"""Per-stock Picks forecast: the K most similar past events of the same setup.

A pick's numbers are the distribution of excess-vs-NIFTY outcomes of the K past
events (same setup, already exited) whose six features at the signal day are
nearest to the stock's own. `validate` decides, per setup, whether that beats
the setup's plain base rate out of sample; if not the setup keeps its average.

NO LOOK-AHEAD: every feature at day p uses bars up to p only; the pool holds only
events whose exit is before the forecast (or test-year start) day.
"""

import numpy as np
import pandas as pd

from backend.lab.splits import yearly_folds

K = 150
MIN_POOL = 300
MIN_TEST = 20          # a test year needs this many events to count its rank IC
IC_SHARE = 0.70        # personalised when IC > 0 in at least this share of test years
FEATURES = ("vol60", "mom", "dist_high", "strength", "regime", "rel20")
YEAR, MONTH = 252, 21


def _frames(t: dict) -> dict[str, pd.DataFrame]:
    close, nifty = t["close"], t["nifty_close"]
    return {
        "vol60": close.pct_change(fill_method=None).rolling(60).std(),
        "mom": close.shift(MONTH) / close.shift(YEAR) - 1,
        "dist_high": close / close.rolling(YEAR, min_periods=YEAR).max() - 1,
        "regime": nifty / nifty.rolling(200, min_periods=200).mean() - 1,
        "rel20": close.pct_change(20, fill_method=None).sub(nifty.pct_change(20, fill_method=None), axis=0),
    }


def features(t: dict, symbol: str, p: int, strength: float, frames: dict | None = None) -> np.ndarray | None:
    """The six features at signal-day position p, or None when any is missing."""
    f = frames or _frames(t)
    x = np.array([f["vol60"][symbol].iat[p], f["mom"][symbol].iat[p], f["dist_high"][symbol].iat[p],
                  strength, f["regime"].iat[p], f["rel20"][symbol].iat[p]], dtype=float)
    return x if np.isfinite(x).all() else None


def event_features(t: dict, ev: pd.DataFrame, fires: pd.DataFrame) -> pd.DataFrame:
    """`ev` (study.events) plus the six features at each event's signal day; events with a gap drop."""
    if ev.empty:
        return ev.assign(**{c: [] for c in FEATURES})
    f = _frames(t)
    days = t["close"].index
    pos = days.get_indexer(ev["signal"])
    cols = t["close"].columns.get_indexer(ev["symbol"])
    out = ev.copy()
    for name in ("vol60", "mom", "dist_high", "rel20"):
        out[name] = f[name].to_numpy()[pos, cols]
    out["regime"] = f["regime"].to_numpy()[pos]
    out["strength"] = fires.to_numpy()[pos, fires.columns.get_indexer(ev["symbol"])]
    out = out[list(ev.columns) + list(FEATURES)]
    return out[np.isfinite(out[list(FEATURES)].to_numpy()).all(axis=1)].reset_index(drop=True)


def _excess(pool: pd.DataFrame) -> np.ndarray:
    return (pool["net"] - pool["nifty"]).to_numpy()


def _scale(pool: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = pool[list(FEATURES)].to_numpy(float)
    mean, std = m.mean(axis=0), m.std(axis=0)
    std[std == 0] = 1.0
    return (m - mean) / std, mean, std


def _nearest(z_pool: np.ndarray, z_x: np.ndarray, k: int) -> np.ndarray:
    """Indices (rows = queries) of the k nearest pool rows; squared Euclidean, chunked."""
    out = []
    for i in range(0, len(z_x), 256):
        q = z_x[i:i + 256]
        d = (q ** 2).sum(1)[:, None] - 2 * q @ z_pool.T + (z_pool ** 2).sum(1)[None, :]
        out.append(np.argpartition(d, k - 1, axis=1)[:, :k])
    return np.vstack(out)


def forecast(pool: pd.DataFrame, x: np.ndarray, k: int = K) -> dict | None:
    """Outcome distribution of the k events nearest `x` (z-scored with the pool's own mean/std)."""
    if len(pool) < MIN_POOL:
        return None
    z, mean, std = _scale(pool)
    idx = _nearest(z, ((np.asarray(x, float) - mean) / std)[None, :], k)[0]
    net, ex = pool["net"].to_numpy()[idx], _excess(pool)[idx]
    q = lambda a: {"median": float(np.median(a)), "p10": float(np.quantile(a, 0.1)), "p90": float(np.quantile(a, 0.9))}
    return {"n": int(k), **q(net), "excess": q(ex), "p_up": float((net > 0).mean()),
            "p_beat_nifty": float((ex > 0).mean())}


def validate(ev: pd.DataFrame) -> dict:
    """Walk-forward by test year (`ev` = event_features): similar forecast vs the pool's base rate.
    -> {skill, ic_years, personalised, years}; skill = 1 - brier_similar / brier_base on P(beat NIFTY)."""
    sim_p, base_p, won, ics = [], [], [], []
    folds = yearly_folds(list(ev["signal"].dt.date), min_train_years=3) if len(ev) else []
    for fold in folds:
        pool = ev[ev["exit"] < pd.Timestamp(fold.test_start)]
        test = ev[ev["signal"].dt.year == fold.year]
        if len(pool) < MIN_POOL or test.empty:
            continue
        z, mean, std = _scale(pool)
        idx = _nearest(z, (test[list(FEATURES)].to_numpy(float) - mean) / std, K)
        pe = _excess(pool)[idx]
        med, p = np.median(pe, axis=1), (pe > 0).mean(axis=1)
        out = _excess(test)
        sim_p += list(p)
        base_p += [float((_excess(pool) > 0).mean())] * len(test)
        won += list(out > 0)
        if len(test) >= MIN_TEST:
            ics.append(float(pd.Series(med).rank().corr(pd.Series(out).rank())))
    if not won:
        return {"skill": None, "ic_years": {"positive": 0, "tested": 0}, "personalised": False}
    w = np.array(won, float)
    bs, bb = float(np.mean((np.array(sim_p) - w) ** 2)), float(np.mean((np.array(base_p) - w) ** 2))
    skill = 1 - bs / bb if bb else None
    pos = sum(i > 0 for i in ics)
    return {"skill": skill, "ic_years": {"positive": pos, "tested": len(ics)},
            "personalised": bool(skill is not None and skill > 0 and ics and pos / len(ics) >= IC_SHARE)}


# --- per-stock range: the pool's standardized quantiles times the stock's own volatility ---
LO, HI = 0.1, 0.9
COVER_TARGET = 0.8


def horizon_vol(vol60, horizon: int):
    """Daily vol60 -> horizon-day vol (sqrt-time); the one unit events are standardized in."""
    return np.asarray(vol60, float) * np.sqrt(horizon)


def standardize(net, vol60, horizon: int):
    return np.asarray(net, float) / horizon_vol(vol60, horizon)


def _range(pool: pd.DataFrame, vol60, horizon: int, centered: bool):
    """(p10, p90) per vol60 entry. centered: the pool's standardized spread around the pool's own
    (setup) median; else the standardized quantiles times vol outright (median = standardized median)."""
    zl, zm, zh = np.quantile(standardize(pool["net"], pool["vol60"], horizon), [LO, 0.5, HI])
    s = horizon_vol(vol60, horizon)
    if centered:
        m = float(pool["net"].median())
        return m + (zl - zm) * s, m + (zh - zm) * s
    return zl * s, zh * s


def scaled_range(pool: pd.DataFrame, vol60: float, horizon: int, centered: bool = True) -> tuple[float, float]:
    lo, hi = _range(pool, vol60, horizon, centered)
    return float(lo), float(hi)


def _pinball(y, q, tau):
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def _score(y, lo, hi) -> dict:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return {"coverage": float(np.mean((y >= lo) & (y <= hi))), "width": float(np.mean(hi - lo)),
            "loss": _pinball(y, lo, LO) + _pinball(y, hi, HI)}


def choose(pooled: dict, variants: dict) -> str | None:
    """Best variant (lowest loss) whose coverage is at least as close to 80% as pooled AND whose loss is lower."""
    gap = lambda m: abs(m["coverage"] - COVER_TARGET)
    ok = {k: m for k, m in variants.items() if gap(m) <= gap(pooled) and m["loss"] < pooled["loss"]}
    return min(ok, key=lambda k: ok[k]["loss"]) if ok else None


def validate_range(ev: pd.DataFrame, horizon: int) -> dict:
    """Walk-forward (same folds/pool as `validate`) on net return: pooled p10/p90 vs vol-scaled.
    -> {n, pooled, vol_scaled (setup median kept), vol_scaled_std (standardized median), each
    {coverage,width,loss}, chosen: None|variant}"""
    ys, lo, hi = [], {}, {}
    for k in ("pooled", "vol_scaled", "vol_scaled_std"):
        lo[k], hi[k] = [], []
    folds = yearly_folds(list(ev["signal"].dt.date), min_train_years=3) if len(ev) else []
    for fold in folds:
        pool = ev[ev["exit"] < pd.Timestamp(fold.test_start)]
        test = ev[ev["signal"].dt.year == fold.year]
        if len(pool) < MIN_POOL or test.empty:
            continue
        ys += list(test["net"])
        a, b = np.quantile(pool["net"], [LO, HI])
        lo["pooled"] += [a] * len(test)
        hi["pooled"] += [b] * len(test)
        for k, c in (("vol_scaled", True), ("vol_scaled_std", False)):
            l, h = _range(pool, test["vol60"], horizon, c)
            lo[k] += list(l)
            hi[k] += list(h)
    if not ys:
        return {"n": 0, "chosen": None}
    y = np.array(ys)
    m = {k: _score(y, lo[k], hi[k]) for k in lo}
    return {"n": len(ys), **m, "chosen": choose(m["pooled"], {k: m[k] for k in ("vol_scaled", "vol_scaled_std")})}
