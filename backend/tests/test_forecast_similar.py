"""Per-stock similar-setup forecast: no look-ahead, planted signal, noise, MIN_POOL, runtime."""

import time

import numpy as np
import pandas as pd
import pytest

from backend.forecast import picks, setups, similar, study
from backend.tests.test_forecast_picks import _frames


def _ev(n=1200, signal=True, seed=0):
    """Events over 2010-2024; excess = 0.1 * -dist_high-ish signal (or noise)."""
    rng = np.random.default_rng(seed)
    sig = pd.Timestamp("2010-01-04") + pd.to_timedelta(np.sort(rng.integers(0, 365 * 15, n)), "D")
    f = rng.normal(size=(n, 6))
    ex = (0.08 * f[:, 2] if signal else 0.0) + rng.normal(0, 0.05, n)
    ev = pd.DataFrame(f, columns=list(similar.FEATURES))
    ev["signal"], ev["exit"] = sig, sig + pd.Timedelta(days=20)
    ev["net"], ev["nifty"] = ex, 0.0
    return ev


def test_features_do_not_see_later_bars():
    t = setups.table(_frames(days=420, n=3))
    p = 350
    x = similar.features(t, "S0", p, 1.0)
    for k in ("close", "open", "high", "low", "volume"):
        t[k] = t[k].copy()
        t[k].iloc[p + 1:] *= 3
    t["nifty_close"] = t["nifty_close"].copy()
    t["nifty_close"].iloc[p + 1:] *= 3
    np.testing.assert_allclose(similar.features(t, "S0", p, 1.0), x)


def test_event_features_match_features_and_pool_excludes_later_exits():
    t = setups.table(_frames(days=420, n=3))
    fires = pd.DataFrame(np.nan, index=t["close"].index, columns=t["close"].columns)
    fires.iloc[::25, 0] = 1.0
    ev = similar.event_features(t, study.events(t, setups.Setup("f", "F", 5, None, None), fires), fires)
    assert len(ev)
    r = ev.iloc[-1]
    p = t["close"].index.get_loc(r["signal"])
    np.testing.assert_allclose(r[list(similar.FEATURES)].to_numpy(float), similar.features(t, r["symbol"], p, 1.0))


def test_planted_dist_high_signal_is_personalised_and_separates_stocks():
    ev = _ev(signal=True)
    v = similar.validate(ev)
    assert v["personalised"] and v["skill"] > 0
    pool = ev[ev["exit"] < pd.Timestamp("2024-01-01")]
    hi = similar.forecast(pool, np.array([0, 0, 2.0, 0, 0, 0]))
    lo = similar.forecast(pool, np.array([0, 0, -2.0, 0, 0, 0]))
    assert hi["excess"]["median"] > lo["excess"]["median"] + 0.05 and hi["n"] == similar.K


def test_noise_is_not_personalised():
    assert similar.validate(_ev(signal=False, seed=3))["personalised"] is False


def test_forecast_none_below_min_pool_and_pool_zscore():
    ev = _ev(n=similar.MIN_POOL - 1)
    assert similar.forecast(ev, np.zeros(6)) is None
    big = _ev(n=500)
    scaled = big.assign(vol60=big["vol60"] * 1000 + 5)  # same ranking after pool z-scoring
    x = np.zeros(6)
    assert similar.forecast(big, x)["median"] == similar.forecast(scaled, np.array([5.0, 0, 0, 0, 0, 0]))["median"]


_real = similar.forecast


def test_compute_personalises_only_validated_setups(monkeypatch):
    t = setups.table(_frames(days=420, n=25))
    monkeypatch.setattr(study, "MIN_N", 1)
    monkeypatch.setattr(similar, "validate", lambda ev: {"skill": 0.1, "ic_years": {"positive": 1, "tested": 1}, "personalised": True})
    monkeypatch.setattr(similar, "MIN_POOL", 5)
    monkeypatch.setattr(similar, "K", 5)
    monkeypatch.setattr(similar, "forecast", lambda pool, x, k=5: None if len(pool) < 5 else _real(pool, x, k))
    results, ps = picks.compute(t)  # smoke: runs end to end, keys present
    assert all("similar" in r for r in results.values())
    for p in ps:
        assert p["forecast"] in ("similar", "setup") and {"median", "p10", "p90", "excess"} <= set(p["expected"])


def test_full_size_runtime_under_five_minutes():
    rng = np.random.default_rng(0)
    days, n = 252 * 17, 236
    idx = pd.bdate_range("2009-01-01", periods=days)
    mk = lambda: pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (days, n)), axis=0)), index=idx,
                              columns=[f"S{i}" for i in range(n)])
    close = mk()
    t = {"close": close, "open": close * (1 + rng.normal(0, 0.003, close.shape)), "high": close, "low": close,
         "volume": pd.DataFrame(rng.uniform(1e5, 4e5, close.shape), index=idx, columns=close.columns),
         "nifty_close": pd.Series(20000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, days))), index=idx)}
    t["nifty_open"] = t["nifty_close"]
    t0 = time.time()
    results, _ = picks.compute(t)
    print({k: (v['n'], v['similar']) for k, v in results.items()})
    took = time.time() - t0
    print(f"compute on {n}x{days}: {took:.1f}s")
    assert took < 300
