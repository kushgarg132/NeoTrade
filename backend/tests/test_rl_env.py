"""backend.rl.env: episodes, state without look-ahead, reward, next_row, dropped short episodes."""

import numpy as np
import pandas as pd

from backend.forecast.setups import Setup
from backend.lab.assumptions import round_trip_return
from backend.rl import env

H = 3
N = 300
P = 250


def _t(n=N, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.DataFrame({s: 100 * np.cumprod(1 + 0.01 * rng.standard_normal(n)) for s in "AB"}, index=idx)
    nifty = pd.Series(100 * np.cumprod(1 + 0.005 * rng.standard_normal(n)), index=idx)
    return {"close": close, "open": close * 1.001, "high": close, "low": close, "volume": close,
            "nifty_close": nifty, "nifty_open": nifty * 0.999}


def _setup(*fire):
    def signals(t):
        out = pd.DataFrame(np.nan, index=t["close"].index, columns=t["close"].columns)
        for symbol, pos in fire:
            out.iloc[pos, out.columns.get_loc(symbol)] = 1.0
        return out
    return Setup("synthetic", "synthetic", H, signals, lambda *a: "")


def test_state_at_day_d_ignores_bars_after_d():
    t, s = _t(), _setup(("A", P))
    base = env.episodes(t, s)
    d = 3
    cut = P + 1 + d  # position of day d
    t2 = {k: v.copy() for k, v in t.items()}
    for k in ("close", "open", "nifty_close", "nifty_open"):
        t2[k].iloc[cut + 1:] = t2[k].iloc[cut + 1:] * 1.5
    alt = env.episodes(t2, s)
    a, b = base[base["day"] <= d], alt[alt["day"] <= d]
    assert len(a) == d
    pd.testing.assert_frame_equal(a[env.STATE + ["exit_reward"]], b[env.STATE + ["exit_reward"]])
    assert not np.isclose(base.loc[base["day"] == d + 1, "pnl"].iat[0], alt.loc[alt["day"] == d + 1, "pnl"].iat[0])


def test_exit_reward_is_round_trip_minus_nifty():
    t, s = _t(), _setup(("A", P))
    rows = env.episodes(t, s)
    r = rows[rows["day"] == 4].iloc[0]
    entry, close = t["open"]["A"].iat[P + 1], t["close"]["A"].iat[P + 1 + 4]
    nifty = t["nifty_close"].iat[P + 1 + 4] / t["nifty_open"].iat[P + 1] - 1
    assert np.isclose(r["exit_reward"], round_trip_return(entry, close) - nifty)
    assert np.isclose(r["pnl"], close / entry - 1) and r["held"] == 4 / env.hmax(s)


def test_next_row_points_to_the_next_day_of_the_same_episode():
    rows = env.episodes(_t(), _setup(("A", P), ("B", P)))
    hm = env.hmax(_setup())
    assert len(rows) == 2 * hm
    for _, r in rows.iterrows():
        if r["day"] == hm:
            assert r["next_row"] == -1
        else:
            n = rows.iloc[int(r["next_row"])]
            assert n["episode"] == r["episode"] and n["day"] == r["day"] + 1
    assert (rows["episode_end"] == rows.groupby("episode")["date"].transform("max")).all()


def test_episode_whose_bars_run_out_before_hmax_is_dropped():
    rows = env.episodes(_t(), _setup(("A", P), ("B", N - 5)))  # B: 5 bars left, HMAX 6 needs 7
    assert rows["episode"].nunique() == 1


def test_subset_remaps_next_row():
    rows = env.episodes(_t(), _setup(("A", P), ("B", P)))
    sub = env.subset(rows, (rows["episode"] == 1).to_numpy())
    assert len(sub) == env.hmax(_setup()) and sub["next_row"].tolist() == [1, 2, 3, 4, 5, -1]
