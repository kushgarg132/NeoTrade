"""`python -m backend.lab rerun`: same data -> exit 0, changed data -> 1, other kinds -> 2."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.factor import report
from backend.forecast import picks, setups
from backend.lab.__main__ import main, rerun
from backend.lab.assumptions import DEFAULT
from backend.lab.runs import LabRunStore
from backend.tests.test_forecast_picks import _frames


def _world(days=2200, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=days)
    closes = pd.DataFrame({f"S{i}": 100 * np.exp(np.cumsum(0.0004 * (i % 5) + 0.01 * rng.standard_normal(days)))
                           for i in range(20)}, index=idx)
    market = pd.Series(100 * np.exp(np.cumsum(np.full(days, 0.0004))), index=idx)
    return closes, market


@pytest.fixture
async def factor_run():
    closes, market = _world()
    db = AsyncMongoMockClient()["t"]
    out = report.run(str(closes.index[300].date()), closes=closes, market=market, series=lambda t: market)
    await report._record_run(db, out)
    run = (await LabRunStore(db).list(kind="factor"))[0]
    return db, run["id"], closes, market


async def test_factor_rerun_matches_and_a_changed_close_differs(factor_run):
    db, run_id, closes, market = factor_run
    code, rep = await rerun(db, run_id, {"closes": lambda: closes, "series": lambda t: market})
    assert code == 0 and rep["fingerprint_then"] == rep["fingerprint_now"] and not rep["deltas"]

    # bars added after the run's window must be ignored: still the same run
    extra = pd.DataFrame(closes.iloc[-5:].to_numpy(), columns=closes.columns,
                         index=pd.bdate_range(closes.index[-1] + pd.Timedelta(days=1), periods=5))
    grown = pd.concat([closes, extra])
    assert (await rerun(db, run_id, {"closes": lambda: grown, "series": lambda t: market}))[0] == 0

    changed = closes.copy()
    changed.iloc[1000, 3] *= 1.5
    code, rep = await rerun(db, run_id, {"closes": lambda: changed, "series": lambda t: market})
    assert code == 1 and rep["fingerprint_then"] != rep["fingerprint_now"]


async def test_study_rerun_matches_and_a_changed_close_differs():
    db = AsyncMongoMockClient()["t"]
    t = setups.table(_frames())
    results, _ = picks.compute(t)
    await picks._record_runs(db, t, results)
    run = (await LabRunStore(db).list(kind="study"))[0]

    async def table():
        return t
    code, rep = await rerun(db, run["id"], {"table": table})
    assert code == 0 and not rep["deltas"]

    frames = _frames()
    frames["S3"].iloc[200, frames["S3"].columns.get_loc("close")] *= 1.5

    async def changed():
        return setups.table(frames)
    code, rep = await rerun(db, run["id"], {"table": changed})
    assert code == 1 and rep["fingerprint_then"] != rep["fingerprint_now"]


async def test_engine_run_and_unknown_id_are_not_rerunnable():
    db = AsyncMongoMockClient()["t"]
    run_id = await LabRunStore(db).record(kind="engine", name="x", config={}, execution=DEFAULT,
                                          window=(date(2024, 1, 1), date(2024, 6, 1)), fingerprint=None,
                                          folds=[], metrics={})
    code, rep = await rerun(db, run_id)
    assert code == 2 and "not re-runnable here" in rep["error"]
    assert (await rerun(db, "nope"))[0] == 2


def test_cli_rejects_unknown_command():
    with pytest.raises(SystemExit):
        main(["bogus", "x"])
