"""Research only (not wired anywhere): can a linear contextual bandit choose
position size and exit for Picks better than the fixed rule?

    python -m backend.forecast.research.bandit_experiment_tool BARS.pkl

BARS.pkl is a pickled DataFrame of `daily_bars` rows (symbol, date, ohlcv).
numpy/pandas only.

Events are the Picks setups' own (study.run + study.events: one per stock per
setup per horizon window). Context on the signal day t uses bars up to t and
setup stats from events that exited before t. Actions: size {0, .5, 1} x exit
{fixed horizon, ATR trail k 1.5/2/3} = 9 distinct (size 0 makes the exit moot).
Exits follow engine/backtest.py: entry at t+1's open, every fill slipped
against us, initial stop entry - k*ATR(t), stop checked on the entry bar too,
then each bar the stop rises to max close since entry - k*ATR(14, SMA, to the
previous bar) and never falls; a bar whose open is through the stop fills at
the open; otherwise close at the bar completing the setup's horizon. Net of
CNC charges (study.net_return on slipped prices). Reward = size x (net -
NIFTY from t+1 open to the exit day's close). NIFTY on a stop day uses that
day's close (the stop fills intraday) -- a small approximation.

Walk-forward per calendar year Y: replay events that exited before Y through
the bandit (bandit feedback: only the chosen arm's reward is seen), freeze,
act on Y's events.
"""

import pickle
import sys
import time

import numpy as np
import pandas as pd

from backend.datalayer.bars import NIFTY
from backend.forecast import setups, study
from backend.suggestions.exits import trail_level

EXITS = (None, 1.5, 2.0, 3.0)  # None = fixed horizon
ACTIONS = [(0.0, None)] + [(s, k) for s in (0.5, 1.0) for k in EXITS]
SEEDS = range(5)
SCALE = 10.0  # rewards x10 inside the bandit so noise is ~1
FEATS = ["setup_momentum", "setup_breakout", "setup_pullback", "setup_low_vol", "p_up", "p_beat", "edge",
         "has_prior", "atr_pct", "d52h", "vratio", "mkt_r20", "mkt_r60", "mkt_above200"]


def load(path: str) -> tuple[dict, pd.DataFrame]:
    with open(path, "rb") as f:
        df = pickle.load(f)
    df["date"] = pd.to_datetime(df["date"])
    frames = {s: g.set_index("date").sort_index() for s, g in df.groupby("symbol")}
    t = setups.table(frames)
    low = pd.DataFrame({s: f["low"] for s, f in frames.items() if s != NIFTY}).reindex(t["close"].index)
    return t, low


def exit_at(o, h, l, c, atr, p: int, horizon: int, k):
    """(exit position, raw exit price) for a signal at p; exit as in engine/backtest.py."""
    e = p + 1
    if k is None:
        return e + horizon, c[e + horizon]
    stop = o[e] - k * atr[p] if np.isfinite(atr[p]) else -np.inf
    if l[e] <= stop:  # entry bar: filled at its open, the rest of the bar can hit the stop
        return e, stop
    high = -np.inf
    for i in range(e + 1, e + horizon + 1):
        if np.isfinite(c[i - 1]):
            high = max(high, c[i - 1])
        if np.isfinite(atr[i - 1]):
            stop = max(stop, trail_level(high, atr[i - 1], k))
        if l[i] <= stop:
            return i, (o[i] if o[i] <= stop else stop)
    return e + horizon, c[e + horizon]


def event_table(t: dict, low: pd.DataFrame) -> pd.DataFrame:
    days = t["close"].index
    c, h, v = t["close"], t["high"], t["volume"]
    tr = pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()]).groupby(level=0).max()
    atr = tr.rolling(14).mean()  # Indicators.atr: SMA of true range
    d52h = c / c.rolling(252, min_periods=20).max() - 1
    vratio = v / v.shift(1).rolling(20, min_periods=20).mean()
    n = t["nifty_close"]
    mkt = pd.DataFrame({"mkt_r20": n / n.shift(20) - 1, "mkt_r60": n / n.shift(60) - 1,
                        "mkt_above200": (n > n.rolling(200).mean()).astype(float)})
    _, fires = study.run(t, setups.SETUPS)
    rows = []
    for s in setups.SETUPS:
        ev = study.events(t, s, fires[s.name]).sort_values("signal").reset_index(drop=True)
        # setup stats known on the signal day: events that already exited
        for i, r in ev.iterrows():
            prior = ev[ev["exit"] < r["signal"]]
            ok = len(prior) >= study.MIN_PRIOR
            x = prior["net"] - prior["nifty"]
            p = days.get_loc(r["signal"])
            sym = r["symbol"]
            row = {"symbol": sym, "setup": s.name, "signal": r["signal"], "pos": p, "horizon": s.horizon,
                   "fixed_net_noslip": r["net"],
                   "p_up": float((prior["net"] > 0).mean()) if ok else 0.5,
                   "p_beat": float((x > 0).mean()) if ok else 0.5,
                   "edge": float(x.mean()) if ok else 0.0, "has_prior": float(ok),
                   "atr_pct": atr[sym].iat[p] / c[sym].iat[p], "d52h": d52h[sym].iat[p],
                   "vratio": vratio[sym].iat[p], **mkt.iloc[p].to_dict()}
            for name in setups.BY_NAME:
                row[f"setup_{name}"] = float(name == s.name)
            rows.append(row)
    df = pd.DataFrame(rows).sort_values(["signal", "symbol"]).reset_index(drop=True)
    df[FEATS] = df[FEATS].fillna(df[FEATS].median())
    arr = {f: t[f].to_numpy() for f in ("open", "high", "close")} | {"low": low.to_numpy(), "atr": atr.to_numpy()}
    cols = {s: j for j, s in enumerate(c.columns)}
    df["_paths"] = [  # (exit pos, raw exit price) per exit choice
        [exit_at(*(arr[f][:, cols[r.symbol]] for f in ("open", "high", "low", "close", "atr")), r.pos, r.horizon, k)
         for k in EXITS] for r in df.itertuples()]
    df["exit_last"] = days[[max(x[0] for x in ps) for ps in df["_paths"]]]  # latest any action could exit
    df["entry_open"] = [arr["open"][r.pos + 1, cols[r.symbol]] for r in df.itertuples()]
    return df


def rewards(df: pd.DataFrame, t: dict, slip_bps: float) -> np.ndarray:
    """events x len(EXITS) excess returns (size 1) at this slippage."""
    s = slip_bps / 10_000
    no, nc = t["nifty_open"].to_numpy(), t["nifty_close"].to_numpy()
    out = np.empty((len(df), len(EXITS)))
    for i, (pos, entry, paths) in enumerate(zip(df["pos"], df["entry_open"], df["_paths"])):
        for j, (xp, price) in enumerate(paths):
            out[i, j] = study.net_return(entry * (1 + s), price * (1 - s)) - (nc[xp] / no[pos + 1] - 1)
    return out


def action_rewards(ex: np.ndarray) -> np.ndarray:
    """events x 9 actions: size x excess of that exit."""
    return np.stack([size * (ex[:, EXITS.index(k)] if size else np.zeros(len(ex))) for size, k in ACTIONS], axis=1)


class LinearBandit:
    """Disjoint ridge per arm. kind 'ucb' (LinUCB, alpha) or 'ts' (linear Thompson, v)."""

    def __init__(self, d: int, kind: str, param: float, rng: np.random.Generator):
        self.A = np.stack([np.eye(d)] * len(ACTIONS))
        self.b = np.zeros((len(ACTIONS), d))
        self.kind, self.param, self.rng = kind, param, rng

    def choose(self, x: np.ndarray, greedy: bool = False) -> int:
        Ainv = np.linalg.inv(self.A)
        theta = np.einsum("aij,aj->ai", Ainv, self.b)
        mean = theta @ x
        if greedy:
            score = mean
        elif self.kind == "ucb":
            score = mean + self.param * np.sqrt(np.einsum("i,aij,j->a", x, Ainv, x))
        else:
            score = np.array([self.rng.multivariate_normal(theta[a], self.param ** 2 * Ainv[a]) @ x
                              for a in range(len(ACTIONS))])
        best = np.flatnonzero(score >= score.max() - 1e-12)
        return int(self.rng.choice(best))

    def update(self, a: int, x: np.ndarray, r: float) -> None:
        self.A[a] += np.outer(x, x)
        self.b[a] += r * x


def metrics(r: np.ndarray, sizes: np.ndarray) -> dict:
    cum = np.cumsum(r)
    dep = sizes > 0
    return {"n": len(r), "mean": float(r.mean()) if len(r) else np.nan,
            "per_deployed": float(r.sum() / sizes.sum()) if sizes.sum() else 0.0,
            "hit": float((r[dep] > 0).mean()) if dep.any() else np.nan,
            "maxdd": float(np.max(np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum])),
            "size0": float((~dep).mean())}


def walk_forward(df: pd.DataFrame, R: np.ndarray, configs: dict) -> dict:
    """policy name -> year -> list of per-seed (action indices). R = events x actions rewards."""
    X_all = df[FEATS].to_numpy(float)
    years = sorted(df["signal"].dt.year.unique())
    out = {}
    for year in years:
        start = pd.Timestamp(year=year, month=1, day=1)
        tr = np.flatnonzero(df["exit_last"] < start)
        te = np.flatnonzero(df["signal"].dt.year == year)
        if len(tr) < 100 or not len(te):
            continue
        mu, sd = X_all[tr].mean(0), X_all[tr].std(0) + 1e-9
        X = np.c_[(X_all - mu) / sd, np.ones(len(X_all))]
        res = {"fixed": [np.full(len(te), ACTIONS.index((1.0, None)))],
               "trail2": [np.full(len(te), ACTIONS.index((1.0, 2.0)))],
               "best_train": [np.full(len(te), int(np.argmax(R[tr].mean(0))))],
               "random": [np.random.default_rng(sd_).integers(len(ACTIONS), size=len(te)) for sd_ in SEEDS]}
        for name, (kind, param, greedy) in configs.items():
            res[name] = []
            for seed in SEEDS:
                rng = np.random.default_rng(seed)
                bandit = LinearBandit(X.shape[1], kind, param, rng)
                # same-day events in seed-random order
                order = tr[np.lexsort((rng.random(len(tr)), df["pos"].to_numpy()[tr]))]
                for i in order:
                    a = bandit.choose(X[i])
                    bandit.update(a, X[i], SCALE * R[i, a])
                res[name].append(np.array([bandit.choose(X[i], greedy) for i in te]))
        out[int(year)] = (te, res)
    return out


def report(df: pd.DataFrame, R: np.ndarray, wf: dict, title: str) -> dict:
    print(f"\n=== {title}")
    sizes_of = np.array([s for s, _ in ACTIONS])
    agg: dict[str, list] = {}
    beats: dict[str, int] = {}
    for year, (te, res) in wf.items():
        fixed_mean = R[te, ACTIONS.index((1.0, None))].mean()
        line = []
        for name, runs in res.items():
            ms = [metrics(R[te, a], sizes_of[a]) for a in runs]
            m = {k: float(np.mean([x[k] for x in ms])) for k in ms[0]}
            agg.setdefault(name, []).append((te, runs))
            beats[name] = beats.get(name, 0) + (m["mean"] > fixed_mean + 1e-12)
            line.append(f"{name:>14}: mean {m['mean']:+.4f} perDep {m['per_deployed']:+.4f} hit {m['hit']:.2f} "
                        f"DD {m['maxdd']:.2f} size0 {m['size0']:.2f}")
        print(f"-- {year} (n={len(te)})")
        print("\n".join("   " + s for s in line))
    print(f"-- aggregate over {len(wf)} test years")
    summary = {}
    fixed_all = None
    for name, items in agg.items():
        n_seeds = len(items[0][1])
        per_seed = []
        for s in range(n_seeds):
            te = np.concatenate([it[0] for it in items])
            a = np.concatenate([it[1][s] for it in items])
            order = np.argsort(df["pos"].to_numpy()[te], kind="stable")
            per_seed.append(metrics(R[te, a][order], sizes_of[a][order]))
        m = {k: float(np.mean([x[k] for x in per_seed])) for k in per_seed[0]}
        m["seed_sd"] = float(np.std([x["mean"] for x in per_seed]))
        if name == "fixed":
            fixed_all = m["mean"]
        summary[name] = m
    for name, m in summary.items():
        m["years_beat_fixed"] = beats[name]
        m["pass"] = name not in ("fixed",) and beats[name] >= min(4, len(wf)) and m["mean"] > fixed_all
        print(f"   {name:>14}: mean {m['mean']:+.4f} (seed sd {m['seed_sd']:.4f}) perDep {m['per_deployed']:+.4f} "
              f"hit {m['hit']:.2f} DD {m['maxdd']:.2f} size0 {m['size0']:.2f} beats fixed {beats[name]}/{len(wf)} "
              f"pass {m['pass']}")
    return summary


def action_mix(wf: dict, name: str) -> str:
    counts = np.zeros(len(ACTIONS))
    for _, res in wf.values():
        for a in res[name]:
            counts += np.bincount(a, minlength=len(ACTIONS))
    counts /= counts.sum()
    return ", ".join(f"{s:g}x{'fixed' if k is None else f'trail{k:g}'} {p:.0%}" for (s, k), p in zip(ACTIONS, counts) if p >= 0.01)


CONFIGS = {  # every bandit variant tried; report the count
    "linucb_a1": ("ucb", 1.0, False),
    "linucb_a1_greedy": ("ucb", 1.0, True),
    "ts_v0.5": ("ts", 0.5, False),
    "ts_v0.5_greedy": ("ts", 0.5, True),
}


def run(path: str) -> None:
    t0 = time.perf_counter()
    t, low = load(path)
    df = event_table(t, low)
    print(f"events {len(df)} ({df['setup'].value_counts().to_dict()}), {df['signal'].min().date()}..{df['signal'].max().date()}, "
          f"build {time.perf_counter() - t0:.0f}s")
    for slip in (10.0, 20.0):
        ex = rewards(df, t, slip)
        R = action_rewards(ex)
        print(f"\nslippage {slip:g} bps: mean excess per exit {dict(zip(['fixed', 'k1.5', 'k2', 'k3'], ex.mean(0).round(4)))}")
        for y, g in df.groupby(df["signal"].dt.year):
            print(f"   {y} n {len(g)}: " + " ".join(f"{e:+.4f}" for e in ex[g.index].mean(0)))
        wf = walk_forward(df, R, CONFIGS)
        report(df, R, wf, f"walk-forward, slippage {slip:g} bps (rewards = fraction of per-trade cap)")
        for name in CONFIGS:
            print(f"   actions {name}: {action_mix(wf, name)}")
        print(f"   actions best_train: {action_mix(wf, 'best_train')}")
    print(f"\nconfigs: {len(CONFIGS)} bandit + 4 baselines, x2 slippage; runtime {time.perf_counter() - t0:.0f}s")


def _check() -> None:
    """Exit semantics: gap-through fills at the open, the stop beats the horizon close, a quiet path exits at the close."""
    o = np.array([10, 10, 10, 10, 8, 9.0])
    c = np.array([10, 10, 10.5, 11, 8.5, 9.0])
    l = np.array([9.9, 9.8, 9.9, 10.6, 7.9, 8.8])
    atr = np.full(6, 0.5)
    assert exit_at(o, None, l, c, atr, 0, 4, None) == (5, 9.0)
    i, px = exit_at(o, None, l, c, atr, 0, 4, 1.0)  # stop rises to 11-0.5 = 10.5; bar 4 opens 8 -> fill at 8
    assert (i, px) == (4, 8.0), (i, px)
    i, px = exit_at(o, None, np.full(6, 9.6), c, atr, 0, 4, 1.0)
    assert (i, px) == (3, 10.0), (i, px)  # stop 10.5-0.5 = 10.0 at bar 3, open 10 <= 10 -> open
    assert exit_at(o, None, np.full(6, 9.6), c, atr, 0, 4, 3.0) == (5, 9.0)


if __name__ == "__main__":
    _check()
    run(sys.argv[1])
