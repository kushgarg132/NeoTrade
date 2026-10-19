"""backend.ml.evaluate: purged folds, rank IC, the pass bar, and the lab_runs record."""

import time
from datetime import datetime, timezone

import bson
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
    # no extra purge: the last sampled date whose label ended before the test year is trained on
    ok = planted[(planted["label_end"].dt.date < fold.test_start) & (planted["date"].dt.date < fold.test_start)]
    assert train["date"].max() == ok["date"].max()


def test_ic_t_uses_non_overlapping_blocks():
    # H=20, STEP=5 -> blocks of 4 sampled dates. A slow wave: overlapping 'monthly' means (6 dates)
    # drift together and look significant, the 12 independent blocks do not.
    n = 48
    ic = pd.Series(0.05 * np.sin(np.arange(n) * 2 * np.pi / 24) + 0.01 * (np.arange(n) % 2),
                   index=pd.bdate_range("2015-01-01", periods=n * 5)[::5])
    t = ev.ic_t(ic, 20)
    blocks = ic.groupby(np.arange(n) // 4).mean()
    assert t == pytest.approx(blocks.mean() / (blocks.std(ddof=1) / 12 ** 0.5))
    assert abs(t) < 2


def test_ic_t_drops_the_short_tail_block():
    ic = pd.Series(np.arange(10.0), index=pd.bdate_range("2015-01-01", periods=10))
    blocks = [ic.iloc[i:i + 4].mean() for i in (0, 4)]  # 10 dates -> 2 full blocks of 4
    assert ev.ic_t(ic, 20) == pytest.approx(np.mean(blocks) / (np.std(blocks, ddof=1) / 2 ** 0.5))


def test_a_test_year_with_no_ic_fails_the_bar():
    df = _table(0.02)
    df = df[~((df["date"].dt.year == 2018) & (df["symbol"] != "S0"))]  # 2018: one name a day, no IC
    r = ev.evaluate_table(df, H)
    assert r["ic_by_year"][2018] != r["ic_by_year"][2018]  # NaN
    assert any("2018" in w for w in ev.passes(r)[1])


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
    assert set(out) == {20, 60} and not out[20]["passed"] and all(o["run_id"] for o in out.values())
    rows = await LabRunStore(db).list(kind="ml")
    assert sorted(r["name"] for r in rows) == ["lgbm_h20", "lgbm_h60"]
    m = rows[0]["metrics"]
    assert m["passed"] is False and m["reasons"] and m["caveats"] == ev.CAVEATS and m["ic_by_year"] == {"2020": -0.1}
    bson.encode(rows[0]["metrics"])  # mongomock accepts anything; real Mongo does not
    assert rows[0]["config"]["horizon"] in (20, 60) and rows[0]["fingerprint"]


@pytest.mark.asyncio
async def test_run_reports_a_failed_record_as_no_run_id(monkeypatch):
    idx = pd.bdate_range("2020-01-01", periods=30)
    t = {"close": pd.DataFrame({"A": np.arange(30.0) + 100}, index=idx)}

    async def load(db, now):
        return t

    async def boom(self, **kw):
        return None  # what LabRunStore.record returns when the insert raises

    monkeypatch.setattr(ev.picks, "load", load)
    monkeypatch.setattr(ev, "evaluate", lambda t, h: {**GOOD, "brier": 0.2, "brier_base": 0.25, "folds": []})
    monkeypatch.setattr(ev.LabRunStore, "record", boom)
    out = await ev.run(AsyncMongoMockClient()["t"], datetime(2026, 1, 1, tzinfo=timezone.utc), horizons=(20,))
    assert out[20]["run_id"] is None
