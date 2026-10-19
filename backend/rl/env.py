"""Exit episodes for Picks: one long table of (episode, held day) rows with a state and the reward for exiting.

An episode is a `study.events` pick. Entry = the open of the day after the signal (as `study.outcome`).
On held day d = 1..HMAX (HMAX = 2 * horizon) the agent decides at day d's close and the exit fills at
the OPEN of day d+1 (tradable: the decision never sees the fill price); day HMAX is a forced exit.
Every state column at day d is a backward window over bars up to d's close, never later (tested).
An episode needs bars through day HMAX+1; one that runs out, or has a missing bar, is dropped.
"""

import numpy as np
import pandas as pd

from backend.forecast import study
from backend.forecast.setups import SETUPS
from backend.lab.assumptions import DEFAULT, round_trip_return

STATE = ["held", "pnl", "nifty_pnl", "vol20", "rel20", "mkt200"] + [f"setup_{s.name}" for s in SETUPS]
VOL_DAYS, REL_DAYS, MKT_DAYS = 20, 20, 200


def hmax(setup) -> int:
    return 2 * setup.horizon


def _series(t: dict) -> dict:
    """Backward-only series: the value at row i uses rows <= i."""
    close, nifty = t["close"], t["nifty_close"]
    return {"vol20": close.pct_change(fill_method=None).rolling(VOL_DAYS).std(),
            "r20": close / close.shift(REL_DAYS) - 1,
            "n20": nifty / nifty.shift(REL_DAYS) - 1,
            "mkt200": nifty / nifty.rolling(MKT_DAYS).mean() - 1}


def episodes(t: dict, setup) -> pd.DataFrame:
    days, hm = t["close"].index, hmax(setup)
    ev = study.events(t, setup, setup.signals(t))
    s = _series(t)
    cols = {c: [] for c in ("episode", "signal_date", "date", "day", *STATE, "exit_reward", "episode_end")}
    d = np.arange(1, hm + 1)
    n_ep = 0
    for symbol, signal in zip(ev["symbol"], ev["signal"]):
        p = days.get_loc(signal)
        if p + 2 + hm >= len(days):
            continue  # bars run out before the HMAX+1 fill: dropped, not truncated
        entry, n_in = t["open"][symbol].iat[p + 1], t["nifty_open"].iat[p + 1]
        idx = p + 1 + d
        close, n_close = t["close"][symbol].to_numpy()[idx], t["nifty_close"].to_numpy()[idx]
        fill, n_fill = t["open"][symbol].to_numpy()[idx + 1], t["nifty_open"].to_numpy()[idx + 1]
        if not (np.isfinite([entry, n_in]).all() and entry > 0 and np.isfinite(close).all() and np.isfinite(n_close).all()
                and np.isfinite(fill).all() and np.isfinite(n_fill).all()):
            continue
        entry = float(entry)
        n_ret = n_fill / n_in - 1  # NIFTY over the same entry open -> exit open
        cols["episode"].append(np.full(hm, n_ep))
        cols["signal_date"].append(np.full(hm, signal.to_datetime64()))
        cols["date"].append(days[idx + 1].to_numpy())  # the fill date
        cols["day"].append(d)
        cols["held"].append(d / hm)
        cols["pnl"].append(close / entry - 1)
        cols["nifty_pnl"].append(n_close / n_in - 1)  # what the reward subtracts, as far as close_d shows
        cols["vol20"].append(s["vol20"][symbol].to_numpy()[idx])
        cols["rel20"].append(s["r20"][symbol].to_numpy()[idx] - s["n20"].to_numpy()[idx])
        cols["mkt200"].append(s["mkt200"].to_numpy()[idx])
        for st in SETUPS:
            cols[f"setup_{st.name}"].append(np.full(hm, float(st.name == setup.name)))
        cols["exit_reward"].append(np.array([round_trip_return(entry, float(c), DEFAULT) for c in fill]) - n_ret)
        cols["episode_end"].append(np.full(hm, days[idx[-1] + 1].to_datetime64()))
        n_ep += 1
    if not n_ep:
        return pd.DataFrame({c: pd.Series(dtype=float) for c in [*cols, "next_row"]})
    out = pd.DataFrame({c: np.concatenate(v) for c, v in cols.items()})
    nxt = np.arange(len(out)) + 1
    nxt[out["day"].to_numpy() == hm] = -1
    out["next_row"] = nxt
    return out


def subset(rows: pd.DataFrame, keep) -> pd.DataFrame:
    """Rows of the `keep` (boolean per row) episodes, renumbered with `next_row` remapped.
    Keep whole episodes only, so every `next_row` stays inside the result."""
    keep = np.asarray(keep, dtype=bool)
    new = np.full(len(rows), -1)
    new[keep] = np.arange(keep.sum())
    out = rows[keep].reset_index(drop=True)
    old = out["next_row"].to_numpy()
    out["next_row"] = np.where(old >= 0, new[np.where(old >= 0, old, 0)], -1)
    return out
