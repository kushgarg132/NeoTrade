"""backend.ml.evaluate: purged folds, rank IC, the pass bar, and the lab_runs record."""

import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.lab.runs import LabRunStore
from backend.ml import evaluate as ev
from backend.ml.features import FEATURES

H = 20
GOOD = {"ic_by_year": {2020: 0.05, 2021: 0.04}, "ic_t": 3.0, "brier_skill": 0.01,
        "portfolio": {"model": 0.02, "momentum": 0.01, "excess_vs_momentum": 0.01}}


def _table(signal: float, seed=0, symbols=40, years=8) -> pd.DataFrame:
    """Every 5th business day of `years` years x `symbols`; r20 drives the next-20-day excess by `signal`."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2012-01-02", periods=years * 260)[::5]
    n = len(dates) * symbols
    df = pd.DataFrame(rng.standard_normal((n, len(FEATURES))), columns=FEATURES)
    df.insert(0, "symbol", np.tile([f"S{i}" for i in range(symbols)], len(dates)))
    df.insert(0, "date", np.repeat(dates, symbols))
    df["nifty"] = 0.005
    df["excess"] = signal * df["r20"] + 0.03 * rng.standard_normal(n)
    df["net"] = df["excess"] + df["nifty"]
    df["up"] = (df["net"] > 0).astype(int)
    df["label_end"] = df["date"] + pd.Timedelta(days=28)  # ~20 trading days
    return df


@pytest.fixture(autouse=True)
def one_thread(monkeypatch):
    # production uses 4 threads; on a shared/busy CPU OpenMP spin-waits make that 25x slower
    monkeypatch.setitem(ev.PARAMS, "num_threads", 1)


@pytest.fixture(scope="module")
def planted():
    return _table(0.02)


def test_planted_signal_passes_every_year_and_is_fast(planted):
    t0 = time.perf_counter()
    r = ev.evaluate_table(planted, H)
    assert time.perf_counter() - t0 < 60
    assert len(r["ic_by_year"]) == 5 and all(v > 0.1 for v in r["ic_by_year"].values())
    assert r["brier_skill"] > 0 and r["portfolio"]["excess_vs_momentum"] > 0
    assert ev.passes(r) == (True, [])


def test_noise_fails_with_an_ic_reason():
    r = ev.evaluate_table(_table(0.0, seed=1), H)
    ok, why = ev.passes(r)
    assert not ok and any("IC" in w for w in why)


def test_no_train_row_ends_after_the_test_year_starts(planted):
    folds = list(ev.split(planted, H))
    assert len(folds) == 5
    for fold, train, test in folds:
        assert train["label_end"].max().date() < fold.test_start
        assert train["date"].max().date() < fold.test_start
        assert {d.year for d in test["date"]} == {fold.year}
    # the purge is real: late-December signals exist in the table but are kept out of the next train set
    fold, train, _ = folds[0]
    december = planted[(planted["date"].dt.year == fold.year - 1) & (planted["date"].dt.month == 12)]
    late = december[december["label_end"].dt.date >= fold.test_start]
    assert len(late) and not train.index.isin(late.index).any()


@pytest.mark.parametrize("change, reason", [
    ({"ic_by_year": {2020: 0.05, 2021: 0.0}}, "IC not positive in 2021"),
    ({"ic_by_year": {2020: -0.01, 2021: 0.04}}, "IC not positive in 2020"),
    ({"ic_t": 1.99}, "t-stat"),
    ({"ic_t": 2.0}, "t-stat"),
    ({"ic_t": None}, "t-stat"),
    ({"brier_skill": 0.0}, "Brier"),
    ({"portfolio": {"model": 0.01, "momentum": 0.01, "excess_vs_momentum": 0.0}}, "momentum"),
])
def test_passes_boundaries_name_each_failing_condition(change, reason):
    ok, why = ev.passes({**GOOD, **change})
    assert not ok and len(why) == 1 and reason in why[0]
    assert ev.passes(GOOD) == (True, [])


def test_all_conditions_failing_lists_all_four():
    bad = {"ic_by_year": {2020: -1.0}, "ic_t": 0.0, "brier_skill": -1.0,
           "portfolio": {"excess_vs_momentum": -1.0}}
    assert len(ev.passes(bad)[1]) == 4


def test_model_score_equal_to_momentum_gives_zero_excess(planted):
    df = planted.assign(score=planted[ev.BASELINE])
    assert ev.top_decile_net(df, "score") == ev.top_decile_net(df, ev.BASELINE)


@pytest.mark.asyncio
async def test_run_records_one_ml_row_per_horizon_even_when_not_passed(monkeypatch):
    idx = pd.bdate_range("2020-01-01", periods=30)
    t = {"close": pd.DataFrame({"A": np.arange(30.0) + 100, "B": np.arange(30.0) + 50}, index=idx)}

    async def load(db, now):
        return t

    bad = {"ic_by_year": {2020: -0.1}, "ic_t": 0.5, "brier": 0.3, "brier_base": 0.25, "brier_skill": -0.2,
           "portfolio": {"model": 0.0, "momentum": 0.01, "excess_vs_momentum": -0.01}, "folds": []}
    monkeypatch.setattr(ev.picks, "load", load)
    monkeypatch.setattr(ev, "evaluate", lambda t, h: bad)
    db = AsyncMongoMockClient()["t"]
    out = await ev.run(db, datetime(2026, 1, 1, tzinfo=timezone.utc), horizons=(20, 60))
    assert set(out) == {20, 60} and not out[20]["passed"]
    rows = await LabRunStore(db).list(kind="ml")
    assert sorted(r["name"] for r in rows) == ["lgbm_h20", "lgbm_h60"]
    m = rows[0]["metrics"]
    assert m["passed"] is False and m["reasons"] and m["caveats"] == ev.CAVEATS and m["ic_by_year"] == {"2020": -0.1}
    assert rows[0]["config"]["horizon"] in (20, 60) and rows[0]["fingerprint"]
