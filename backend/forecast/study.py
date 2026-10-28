"""Event study and walk-forward calibration for the Picks setups.

An event: the setup fires on day t (close known), entry at t+1's open, exit
at the close of t+1+H. Net return is gross minus adverse slippage and NSE delivery round-trip
charges from `engine/execution/costs.py::calculate_indian_costs` (CNC, on a
NOTIONAL position); NIFTY's return is taken over the identical window.

One event per stock per setup per horizon window: a signal inside a
previous event's window is skipped, so overlapping copies of one move are
not counted as independent evidence.
"""

from statistics import NormalDist

import numpy as np
import pandas as pd

from backend.lab.assumptions import DEFAULT, Execution, round_trip_return
from backend.lab.splits import yearly_folds

# Rupees per position: sets the flat parts (brokerage cap, DP charge). The AI account's per-trade cap
# (admin pref, 2026-10-23), not 100k: at 100k the DP charge is 2 bps, at 5k it is 32 (audit T6, 2026-10-24).
NOTIONAL = 5_000.0
MIN_PRIOR = 30        # walk-forward: a year is only tested once this many past events have matured
MIN_N = 100           # picks come only from setups with at least this many events
STOPPED = 5           # trading days with no close after an exit day before the stock counts as stopped, not late


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
    or None while it has not matured / a bar is missing. A stock that stopped trading inside the window
    (no close from the exit day on, STOPPED days later) exits at its last close: dropping it would hide
    halts and delistings, mostly losers."""
    days = t["close"].index
    k = p + 1 + horizon
    if k >= len(days):
        return None
    entry = t["open"][symbol].iat[p + 1]
    close = t["close"][symbol]
    exit_ = close.iat[k]
    if np.isnan(exit_) and k + STOPPED < len(days) and close.iloc[k:].isna().all():
        last = close.iloc[p + 1:k].last_valid_index()
        exit_ = close[last] if last is not None else np.nan
    n_in, n_out = t["nifty_open"].iat[p + 1], t["nifty_close"].iat[p + 1 + horizon]
    if not all(np.isfinite([entry, exit_, n_in, n_out])) or entry <= 0:
        return None
    entry, exit_ = float(entry), float(exit_)
    return days[p + 1], days[p + 1 + horizon], exit_ / entry - 1, net_return(entry, exit_), float(n_out / n_in - 1)


def events(t: dict, setup, fires: pd.DataFrame, dedup: bool = True) -> pd.DataFrame:
    """dedup=False keeps overlapping signals too (the baseline: one row per stock per month)."""
    rows = []
    for symbol in fires.columns:
        col = fires[symbol].to_numpy()
        for p in kept(col, setup.horizon) if dedup else np.flatnonzero(~np.isnan(col)):
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
        "excess_p10": float(excess.quantile(0.1)),
        "excess_p90": float(excess.quantile(0.9)),
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


ADJ_MIN_T = 2.0   # one setup tested alone: a setup has an edge when its adjusted excess is > 0 with this month-block t
BOOT = 2000


def min_t(tests: int) -> float:
    """ADJ_MIN_T's two-sided 5% raised for `tests` setups graded at once (Bonferroni): 8 setups -> 2.73. With 8
    graded at t >= 2 one lucky A is likely; the 2026-10-27 survivorship rerun flipped 3 of 8 grades (audit follow-up)."""
    return NormalDist().inv_cdf(1 - 0.025 / max(tests, 1))


def members_only(t: dict, fires: pd.DataFrame) -> pd.DataFrame:
    """`fires` kept only where the stock was in the index that day (`t["member"]`, forecast/members.py)."""
    m = t.get("member")
    return fires if m is None else fires.where(m.reindex(index=fires.index, columns=fires.columns, fill_value=False))


def every_month(t: dict) -> pd.DataFrame:
    """Baseline fires: every stock on each month's first trading day (what a random pick earns in this universe)."""
    from backend.forecast.setups import _month_starts

    c = t["close"]
    out = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    out.loc[_month_starts(c.index)] = 1.0
    return members_only(t, out.where(c.notna()))


class _Horizon:
    def __init__(self, horizon):
        self.horizon = horizon


def baseline_by_month(t: dict, horizon: int) -> pd.Series:
    """Mean excess over NIFTY of ALL universe stocks over `horizon`, by signal month. Today's universe beats NIFTY
    on average (survivorship; the member mask cuts it, gaps in the archived lists leave some), so a setup must beat THIS, not zero."""
    ev = events(t, _Horizon(horizon), every_month(t), dedup=False)  # every month its own baseline, even when h spans several
    return (ev["net"] - ev["nifty"]).groupby(ev["signal"].dt.to_period("M")).mean()


def basket(ev: pd.DataFrame, baseline: pd.Series, wf: dict) -> dict:
    """The setup held as a basket: every pick of a signal month bought together (equal weight), out of sample
    (the years `walk_forward` tested). A single stock over a few weeks is mostly noise; the edge shows across
    a basket. `beat_nifty` / `beat_average` = share of months the basket beat NIFTY / the average stock;
    `years_positive` = share of test years whose mean excess over the average stock was above zero."""
    none = {"months": 0, "beat_nifty": None, "median_vs_nifty": None, "beat_average": None, "years_positive": None}
    years = [y["year"] for y in wf["years"]]
    o = ev[ev["signal"].dt.year.isin(years)] if not ev.empty else ev
    if len(o) < 5:
        return none
    month = o["signal"].dt.to_period("M")
    ex = o["net"] - o["nifty"]
    frame = pd.DataFrame({"m": month, "ex": ex, "adj": ex - month.map(baseline).fillna(baseline.mean()),
                          "y": o["signal"].dt.year})
    by_month = frame.groupby("m").agg(n=("ex", "size"), ex=("ex", "mean"), adj=("adj", "mean"))
    by_month = by_month[by_month["n"] >= BASKET_MIN]
    by_year = frame.groupby("y")["adj"].mean()
    if by_month.empty:
        return none
    return {"months": int(len(by_month)), "beat_nifty": float((by_month["ex"] > 0).mean()),
            "median_vs_nifty": float(by_month["ex"].median()), "beat_average": float((by_month["adj"] > 0).mean()),
            "years_positive": float((by_year > 0).mean())}


BASKET_MIN = 3  # a month counts as a basket from this many picks


def adjusted_edge(ev: pd.DataFrame, baseline: pd.Series, wf: dict, need_t: float = ADJ_MIN_T) -> dict:
    """Out-of-sample (the years `walk_forward` tested) mean of excess over NIFTY minus the baseline of the signal
    month, with a month-block bootstrap t. `edge` = mean > 0, t >= need_t, and the mean is above zero in both
    the earlier and the later half of the tested months (`halves`): an edge that lives in one stretch is luck."""
    none = {"oos_n": 0, "excess": None, "t": None, "halves": None, "edge": False}
    years = [y["year"] for y in wf["years"]]
    o = ev[ev["signal"].dt.year.isin(years)] if not ev.empty else ev
    if len(o) < 5:
        return none
    month = o["signal"].dt.to_period("M")
    adj = (o["net"] - o["nifty"] - month.map(baseline).fillna(baseline.mean())).to_numpy()
    g = pd.DataFrame({"m": month.astype(str).to_numpy(), "a": adj}).groupby("m")["a"].agg(["sum", "count"])
    s, n = g["sum"].to_numpy(), g["count"].to_numpy()
    mean = float(s.sum() / n.sum())
    idx = np.random.default_rng(0).integers(0, len(s), (BOOT, len(s)))
    sd = (s[idx].sum(1) / n[idx].sum(1)).std(ddof=1)
    t_ = mean / sd if sd > 0 else None
    half = len(s) // 2  # groupby sorts the "YYYY-MM" keys, so this splits earlier from later months
    halves = [float(s[:half].sum() / n[:half].sum()) if half else None, float(s[half:].sum() / n[half:].sum())]
    return {"oos_n": int(len(o)), "excess": mean, "t": None if t_ is None else float(t_), "need_t": need_t,
            "halves": halves,
            "edge": bool(mean > 0 and t_ is not None and t_ >= need_t and all(h is not None and h > 0 for h in halves))}


ATR_DAYS = 14
STOP_ATR = 2.0  # a stop no further than this many ATRs below entry (forecast/picks.py::levels)


def levels_exit(t: dict, ev: pd.DataFrame, p10: float, median: float) -> pd.DataFrame:
    """`ev` with `net` re-priced under the exits the autopilot trades (forecast/picks.py::levels): stop at the
    tighter of entry x (1 + p10) and STOP_ATR x ATR below entry, target at entry x (1 + median); the first touch
    inside the horizon exits (a stop before a target on the same bar, a gap through either fills at the open),
    else the horizon close as before. `_levels_exit` passes each test year the p10/median of the events that
    matured before it began, so the comparison stays out of sample."""
    if ev.empty:
        return ev
    days = t["close"].index
    o, h, l, c = (t[k] for k in ("open", "high", "low", "close"))
    prev = c.shift()
    atr = np.fmax(np.fmax(h - l, (h - prev).abs()), (l - prev).abs()).rolling(ATR_DAYS).mean()
    col = {sym: i for i, sym in enumerate(c.columns)}
    O, H, L, C, A = (x.to_numpy() for x in (o, h, l, c.ffill(), atr))  # ffill: a stopped stock's last close (outcome)
    nets = []
    for sym, entry_day, exit_day in zip(ev["symbol"], ev["entry"], ev["exit"]):
        j, i, k = col[sym], days.get_loc(entry_day), days.get_loc(exit_day)
        e = O[i, j]
        stops = [e * (1 + p10)] if p10 < 0 else []
        if np.isfinite(A[i - 1, j]):
            stops.append(e - STOP_ATR * A[i - 1, j])
        stop = max(stops) if stops else -np.inf
        target = e * (1 + median) if median > 0 else np.inf
        out = C[k, j]
        for d in range(i, k + 1):
            if L[d, j] <= stop:
                out = min(O[d, j], stop) if d > i else stop
                break
            if H[d, j] >= target:
                out = max(O[d, j], target) if d > i else target
                break
        nets.append(net_return(float(e), float(out)))
    return ev.assign(net=nets)


def run(t: dict, setups) -> tuple[dict, dict]:
    """-> ({setup: stats + walk_forward}, {setup: fires frame})."""
    results, all_fires, base = {}, {}, {}
    need = min_t(len(setups))
    for s in setups:
        fires = members_only(t, s.signals(t))
        ev = events(t, s, fires)
        if s.horizon not in base:
            base[s.horizon] = baseline_by_month(t, s.horizon)
        wf = walk_forward(ev)
        st, adj = stats(ev), adjusted_edge(ev, base[s.horizon], wf, need)
        results[s.name] = {"setup": s.name, "label": s.label, "horizon": s.horizon, "experimental": getattr(s, "experimental", False),
                           **st, "walk_forward": wf, "adjusted": adj, "basket": basket(ev, base[s.horizon], wf),
                           "levels_exit": _levels_exit(t, ev, st, base[s.horizon], wf, adj)}
        all_fires[s.name] = fires
    return results, all_fires


def _levels_exit(t, ev, st, baseline, wf, adj) -> dict:
    """The stop/target exit's adjusted excess and t beside the horizon exit's; `better` = it earned more over
    the same out-of-sample events, so the autopilot trades the levels only then (autopilot/picks.py)."""
    if not st.get("n"):
        return {"excess": None, "t": None, "better": False}
    parts = []
    for y in wf["years"]:  # each test year priced with the p10/median known on its Jan 1, as walk_forward
        prior = ev.loc[ev["exit"] < pd.Timestamp(y["year"], 1, 1), "net"]
        test = ev[ev["signal"].dt.year == y["year"]]
        parts.append(levels_exit(t, test, float(prior.quantile(0.1)), float(prior.median())))
    lv = adjusted_edge(pd.concat(parts) if parts else ev.iloc[:0], baseline, wf)
    better = lv["excess"] is not None and adj["excess"] is not None and lv["excess"] > adj["excess"]
    return {"excess": lv["excess"], "t": lv["t"], "better": bool(better)}
