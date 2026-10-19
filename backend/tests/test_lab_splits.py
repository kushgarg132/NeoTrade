from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.factor.model import Params
from backend.lab.splits import yearly_folds


def test_rolling_three_year_window():
    days = pd.bdate_range("2010-01-01", "2015-12-31").date
    f = yearly_folds(days, min_train_years=3, window_years=3)
    assert [x.year for x in f] == [2013, 2014, 2015]
    assert f[0].train_start == date(2010, 1, 1) and f[0].test_start == date(2013, 1, 1)
    assert f[0].test_end == date(2014, 1, 1) and f[1].train_start == date(2011, 1, 1)


def test_purge_drops_trading_days_before_test():
    days = pd.bdate_range("2010-01-01", "2012-12-31").date
    f = yearly_folds(days, min_train_years=2, purge_days=5)[0]
    assert f.train_end == days[list(days).index(date(2012, 1, 2)) - 5]


def test_embargo_trims_train_start_after_an_earlier_test_year():
    days = pd.bdate_range("2010-01-01", "2015-12-31").date
    f = yearly_folds(days, min_train_years=3, window_years=1, embargo_days=3)[0]
    assert f.train_start == days[list(days).index(date(2012, 1, 2)) + 3]


def test_too_little_history_gives_no_folds():
    assert yearly_folds(pd.bdate_range("2020-01-01", "2020-12-31").date, min_train_years=3) == []


def _factor_run():
    from backend.factor.validate import walk_forward
    from backend.tests.test_factor_backtest import _world

    closes, market = _world(days=1500, seed=7)
    start, end = closes.index[260], closes.index[-1]
    variants = [Params(top_n=5, buffer=8, target_vol=None), Params(top_n=8, buffer=12, target_vol=None)]
    wf = walk_forward(closes, market, start, end, variants, in_sample_years=2)
    return {y: (p.top_n, p.buffer) for y, p in wf.chosen.items()}, round(float(wf.returns.sum()), 10), len(wf.returns)


def _study_events():
    rng = np.random.default_rng(3)
    rows = []
    for year in range(2018, 2023):
        for _ in range(40):
            s = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=int(rng.integers(0, 365)))
            rows.append((s, s + pd.Timedelta(days=30), float(rng.normal(0.01, 0.05)), float(rng.normal(0, 0.02))))
    return pd.DataFrame(rows, columns=["signal", "exit", "net", "nifty"])


def _study_run():
    from backend.forecast import study
    return study.walk_forward(_study_events())


def test_factor_walk_forward_unchanged():
    assert _factor_run() == ({2021: (8, 12), 2022: (8, 12), 2023: (8, 12), 2024: (8, 12)}, 0.9764361297, 977)


def test_study_walk_forward_unchanged():
    wf = _study_run()
    assert [(y["year"], y["n"], y["prior_n"]) for y in wf["years"]] == [(2019, 40, 37), (2020, 40, 78), (2021, 40, 117), (2022, 40, 153)]
    assert wf["brier"] == pytest.approx(0.2474740563291335, abs=1e-12)
