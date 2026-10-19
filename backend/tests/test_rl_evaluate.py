"""backend.rl.evaluate: purged yearly folds, train-only baselines, the pass bar, the lab_runs record."""

import time
from datetime import datetime, timezone

import bson
import numpy as np
import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.forecast.setups import Setup
from backend.lab.runs import LabRunStore
from backend.rl import evaluate as ev
from backend.rl.env import STATE, episodes

H = 4  # fixed exit = day 4, HMAX = 8
FAST, SLOW = [.04, .06, .03, 0, -.02, -.02, -.02, -.02], [.005, .02, .04, .07, .03, 0, -.02, -.02]
# A picks peak on day 2 (a +4% first day gives it away), B picks on day 4: the mean best day is 3
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prices(planted: bool, seed=0, symbols=12, years=12, every=10):
    """Flat 100 plus noise; a pick every `every` days per name follows FAST or SLOW (random) if planted."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=years * 260)
    n = len(idx)
    walk = lambda: 100 * np.cumprod(1 + 0.01 * rng.standard_normal(n))  # noqa: E731
    close = {s: (100 + 0.2 * rng.standard_normal(n) if planted else walk()) for s in (f"S{i}" for i in range(symbols))}
    fires = pd.DataFrame(np.nan, index=idx, columns=list(close))
    for s in close:
        for p in range(300, n - 12, every):
            fires.iloc[p, fires.columns.get_loc(s)] = 1.0
            if planted:
                bump = FAST if rng.random() < 0.5 else SLOW
                close[s][p + 1] = 100  # day 0
                close[s][p + 2:p + 10] = 100 * (1 + np.array(bump) * rng.uniform(0.8, 1.2))
                close[s][p + 10:p + every + 1] = 100
    close = pd.DataFrame(close, index=idx)
    nifty = pd.Series(100.0, index=idx)
    t = {"close": close, "open": close.shift(1).bfill(), "high": close, "low": close, "volume": close,
         "nifty_close": nifty, "nifty_open": nifty}
    return t, Setup("synthetic", "synthetic", H, lambda _t: fires, lambda *a: "")


@pytest.fixture(scope="module")
def planted():
    t, s = _prices(True)
    return episodes(t, s), s


def test_planted_exit_timing_passes_and_is_fast(planted):
    rows, s = planted
    t0 = time.perf_counter()
    r = ev.evaluate_rows(rows, s)
    assert time.perf_counter() - t0 < 60
    assert len(r["improvement_by_year"]) == 8 and all(v > 0 for v in r["improvement_by_year"].values())
    assert 2.5 < r["rules"]["policy"]["mean_days"] < 3.5
    assert r["rules"]["policy"]["mean_excess"] > r["rules"]["best_fixed"]["mean_excess"] > r["rules"]["fixed"]["mean_excess"]
    # the planted baseline never loses money (drawdown 0), so a policy's few-bp dip is the only clause that can bite
    ok, why = ev.passes(r)
    assert all("drawdown" in w for w in why) and r["rules"]["policy"]["max_drawdown"] < 0.01


def test_noise_fails_with_reasons():
    t, s = _prices(False, seed=3)
    ok, why = ev.passes(ev.evaluate_rows(episodes(t, s), s))
    assert not ok and why


class Hold:
    """The fixed rule dressed as a policy: every episode exits at the setup's horizon."""
    def __init__(self, rows):
        self.ids = rows["episode"].unique()

    def exit_days(self, rows):
        return pd.Series(H, index=rows["episode"].unique())


def test_always_hold_to_the_horizon_policy_equals_fixed_exactly(planted):
    rows, s = planted
    r = ev.evaluate_rows(rows, s, fit=lambda train, iterations: Hold(train))
    assert r["rules"]["policy"] == r["rules"]["fixed"]


def _hand_rows(peaks: dict[int, int], per_year=30):
    """Hand-built episodes, one block per signal year: every pick's reward peaks on `peaks[year]`."""
    out = []
    ep = 0
    for year, peak in peaks.items():
        for i in range(per_year):
            sig = pd.Timestamp(year, 1, 5) + pd.Timedelta(days=9 * i)
            for d in range(1, 9):
                row = dict.fromkeys(STATE, 0.0)
                row.update(episode=ep, signal_date=sig, date=sig + pd.Timedelta(days=d), day=d, held=d / 8,
                           exit_reward=0.05 - 0.01 * abs(d - peak), episode_end=sig + pd.Timedelta(days=8),
                           next_row=-1 if d == 8 else len(out) + 1)
                out.append(row)
            ep += 1
    return pd.DataFrame(out)


def test_best_fixed_day_is_chosen_on_train_not_test():
    rows = _hand_rows({2014: 3, 2015: 3, 2016: 3, 2017: 6})
    r = ev.evaluate_rows(rows, Setup("s", "s", 4, None, None), fit=lambda train, iterations: Hold(train))
    assert r["rules"]["best_fixed"]["mean_days"] == 3.0  # the test-year best (day 6) is not used
    assert r["rules"]["best_fixed"]["mean_excess"] == pytest.approx(0.05 - 0.03)
    assert r["baseline"]["choice"] == {"2017": "best_fixed"}  # day 3 beat the horizon (day 4) on train


def test_train_episodes_that_end_in_the_test_year_are_dropped():
    rows = _hand_rows({2014: 3, 2015: 3, 2016: 3, 2017: 3})
    one = rows["episode"] == rows.loc[rows["signal_date"].dt.year == 2016, "episode"].iloc[-1]
    rows.loc[one, "signal_date"] = pd.Timestamp(2016, 12, 29)
    rows.loc[one, "episode_end"] = pd.Timestamp(2017, 1, 6)
    ends = []
    ev.evaluate_rows(rows, Setup("s", "s", 4, None, None),
                     fit=lambda train, iterations: ends.append(train["episode_end"].max()) or Hold(train))
    assert ends[0] < pd.Timestamp(2017, 1, 1)


RES = {"improvement_by_year": {str(y): 0.01 for y in range(2012, 2020)}, "mean_improvement": 0.01, "t": 3.0, "hit_years": 1.0,
       "rules": {"policy": {"max_drawdown": 0.10}}, "baseline": {"max_drawdown": 0.10}}


def _with(**kw):
    out = {**RES, **kw}
    if "dd" in kw:
        out = {**RES, "rules": {"policy": {"max_drawdown": kw["dd"]}}}
    return out


@pytest.mark.parametrize("change, reason", [
    ({"mean_improvement": 0.0}, "mean improvement"),
    ({"t": 1.99}, "t-stat"),
    ({"t": None}, "t-stat"),
    ({"hit_years": 0.69}, "of years"),
    ({"dd": 0.1001}, "drawdown"),
])
def test_passes_boundaries(change, reason):
    ok, why = ev.passes(_with(**change))
    assert not ok and len(why) == 1 and reason in why[0]


def test_passes_accepts_the_boundaries_themselves():
    assert ev.passes(_with(t=2.0, hit_years=0.70, dd=0.10)) == (True, [])


def test_fewer_than_min_test_years_fails():
    ok, why = ev.passes(_with(improvement_by_year={"2020": 0.01, "2021": 0.01}))
    assert not ok and why == [f"only 2 test years (< {ev.MIN_TEST_YEARS})"]


def test_no_test_years_fails():
    assert ev.passes(ev._empty())[0] is False


FAKE = {"rules": {k: {"mean_excess": 0.0, "max_drawdown": 0.2, "mean_days": 4.0} for k in ("policy", "fixed", "best_fixed")},
        "baseline": {"mean_excess": 0.01, "max_drawdown": 0.1, "mean_days": 4.0, "choice": {"2020": "fixed"}},
        "improvement_by_year": {"2020": -0.01}, "mean_improvement": -0.01, "t": None, "hit_years": 0.0, "folds": []}


@pytest.mark.asyncio
async def test_run_records_one_rl_row_per_setup_even_when_not_passed(monkeypatch):
    idx = pd.bdate_range("2020-01-01", periods=30)

    async def load(db, now):
        return {"close": pd.DataFrame({"A": np.arange(30.0) + 100}, index=idx)}

    monkeypatch.setattr(ev.picks, "load", load)
    monkeypatch.setattr(ev, "evaluate", lambda t, s: FAKE)
    db = AsyncMongoMockClient()["t"]
    out = await ev.run(db, START)
    assert set(out) == {s.name for s in ev.SETUPS} and not any(o["passed"] for o in out.values())
    assert all(o["run_id"] for o in out.values())
    rows = await LabRunStore(db).list(kind="rl")
    assert sorted(r["name"] for r in rows) == sorted(f"fqi_exit:{s.name}" for s in ev.SETUPS)
    m = rows[0]["metrics"]
    assert m["setups_passed"] == 0 and m["family_passed"] is False
    assert m["passed"] is False and m["reasons"] and m["caveats"] == ev.CAVEATS
    assert m["improvement_by_year"] == {"2020": -0.01} and m["baseline"]["choice"] == {"2020": "fixed"}
    bson.encode(rows[0]["metrics"])  # mongomock accepts anything; real Mongo does not
    bson.encode(rows[0]["config"])
    assert rows[0]["fingerprint"] and rows[0]["config"]["iterations"] == 5


@pytest.mark.asyncio
async def test_a_real_result_is_bson_safe(planted, monkeypatch):
    rows, s = planted
    r = ev.evaluate_rows(rows, s)
    bson.encode(ev._metrics(r, *ev.passes(r)))


def test_main_prints_not_recorded_and_exits_1(monkeypatch, capsys):
    async def fake_run(db, now, setups):
        return {"momentum": {**FAKE, "setups_passed": 0, "family_passed": False, "passed": False, "reasons": ["x"], "run_id": None}}

    class Db:
        db = None

        async def connect_to_database(self):
            pass

    monkeypatch.setattr(ev, "run", fake_run)
    monkeypatch.setattr("backend.database.db", Db())
    assert ev.main([]) == 1
    assert "NOT RECORDED" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("n_pass, family", [(1, False), (2, True)])
async def test_family_passes_only_with_two_setups(monkeypatch, n_pass, family):
    idx = pd.bdate_range("2020-01-01", periods=30)

    async def load(db, now):
        return {"close": pd.DataFrame({"A": np.arange(30.0) + 100}, index=idx)}

    names = [s.name for s in ev.SETUPS]
    monkeypatch.setattr(ev.picks, "load", load)
    monkeypatch.setattr(ev, "evaluate", lambda t, s: {**FAKE, "name": s.name})
    monkeypatch.setattr(ev, "passes", lambda r: (names.index(r["name"]) < n_pass, []))
    db = AsyncMongoMockClient()["t"]
    out = await ev.run(db, START)
    assert all(o["family_passed"] is family and o["setups_passed"] == n_pass for o in out.values())
    assert all(r["metrics"]["family_passed"] is family for r in await LabRunStore(db).list(kind="rl"))
