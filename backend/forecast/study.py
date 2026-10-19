"""Event study and walk-forward calibration for the Picks setups.

An event: the setup fires on day t (close known), entry at t+1's open, exit
at the close of t+1+H. Net return is gross minus adverse slippage and NSE delivery round-trip
charges from `engine/execution/costs.py::calculate_indian_costs` (CNC, on a
NOTIONAL position); NIFTY's return is taken over the identical window.

One event per stock per setup per horizon window: a signal inside a
previous event's window is skipped, so overlapping copies of one move are
not counted as independent evidence.
"""

import numpy as np
import pandas as pd

from backend.lab.assumptions import DEFAULT, Execution, round_trip_return
from backend.lab.splits import yearly_folds

NOTIONAL = 100_000.0  # rupees per position: sets the flat parts (brokerage cap, DP charge)
MIN_PRIOR = 30        # walk-forward: a year is only tested once this many past events have matured
MIN_N = 100           # picks come only from setups with at least this many events


def net_return(entry: float, exit_: float, ex: Execution = DEFAULT) -> float:
    return round_trip_return(entry, exit_, ex, notional=NOTIONAL)


def kept(fires: np.ndarray, horizon: int) -> list[int]:
    """Positions of the signals that count: each at least horizon+1 days
    after the last one kept, so its entry (t+1) comes after that one's exit."""
    out, last = [], None
    for p in np.flatnonzero(~np.isnan(fires)):
        if last is None or p >= last + horizon + 1:
            out.append(p)
            last = p
    return out


def outcome(t: dict, symbol: str, p: int, horizon: int):
    """(entry date, exit date, gross, net, nifty) for a signal at position p,
    or None while it has not matured / a bar is missing."""
    days = t["close"].index
    if p + 1 + horizon >= len(days):
        return None
    entry = t["open"][symbol].iat[p + 1]
    exit_ = t["close"][symbol].iat[p + 1 + horizon]
    n_in, n_out = t["nifty_open"].iat[p + 1], t["nifty_close"].iat[p + 1 + horizon]
    if not all(np.isfinite([entry, exit_, n_in, n_out])) or entry <= 0:
        return None
    entry, exit_ = float(entry), float(exit_)
    return days[p + 1], days[p + 1 + horizon], exit_ / entry - 1, net_return(entry, exit_), float(n_out / n_in - 1)


def events(t: dict, setup, fires: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol in fires.columns:
        for p in kept(fires[symbol].to_numpy(), setup.horizon):
            o = outcome(t, symbol, p, setup.horizon)
            if o:
                rows.append((symbol, fires.index[p], *o))
    return pd.DataFrame(rows, columns=["symbol", "signal", "entry", "exit", "gross", "net", "nifty"])


def stats(ev: pd.DataFrame) -> dict:
    if ev.empty:
        return {"n": 0}
    excess = ev["net"] - ev["nifty"]
    return {
        "n": int(len(ev)),
        "median": float(ev["net"].median()),
        "p10": float(ev["net"].quantile(0.1)),
        "p90": float(ev["net"].quantile(0.9)),
        "p_up": float((ev["net"] > 0).mean()),
        "p_beat_nifty": float((excess > 0).mean()),
        "mean_excess": float(excess.mean()),
        "median_excess": float(excess.median()),
    }


def walk_forward(ev: pd.DataFrame) -> dict:
    """For each year Y, predict P(up) from events that matured before Y
    began, then score it against Y's own events. Brier and out-of-sample
    excess pool every tested event."""
    years, preds, outs, excess = [], [], [], []
    folds = yearly_folds(list(ev["signal"].dt.date), min_train_years=0) if not ev.empty else []
    for fold in folds:
        year, start = fold.year, pd.Timestamp(fold.test_start)
        prior = ev[ev["exit"] < start]
        test = ev[ev["signal"].dt.year == year]
        if len(prior) < MIN_PRIOR or test.empty:
            continue
        p = float((prior["net"] > 0).mean())
        won = (test["net"] > 0).to_numpy(float)
        x = (test["net"] - test["nifty"]).to_numpy()
        years.append({
            "year": int(year), "n": int(len(test)), "prior_n": int(len(prior)),
            "predicted_p_up": p, "realised_p_up": float(won.mean()), "mean_excess": float(x.mean()),
        })
        preds += [p] * len(won)
        outs += list(won)
        excess += list(x)
    if not years:
        return {"years": [], "brier": None, "oos_n": 0, "oos_excess": None, "oos_t": None, "edge": False}
    oos = float(np.mean(excess))
    se = float(np.std(excess, ddof=1) / np.sqrt(len(excess))) if len(excess) > 1 else 0.0
    return {
        "years": years,
        "brier": float(np.mean((np.array(preds) - np.array(outs)) ** 2)),
        # t overstates confidence: events in one month move together.
        "oos_n": len(excess), "oos_excess": oos, "oos_t": oos / se if se else None, "edge": oos > 0,
    }


def run(t: dict, setups) -> tuple[dict, dict]:
    """-> ({setup: stats + walk_forward}, {setup: fires frame})."""
    results, all_fires = {}, {}
    for s in setups:
        fires = s.signals(t)
        ev = events(t, s, fires)
        results[s.name] = {"setup": s.name, "label": s.label, "horizon": s.horizon,
                           **stats(ev), "walk_forward": walk_forward(ev)}
        all_fires[s.name] = fires
    return results, all_fires
