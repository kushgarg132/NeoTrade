"""Out-of-sample validation for the factor strategy.

walk_forward: every variant in a small grid is simulated once; then, for
each test year, the variant with the best Sharpe over the previous
`in_sample_years` is chosen and only its NEXT year counts. The stitched
out-of-sample returns are what the gate judges -- never the best
in-sample curve.

deflated_sharpe (Bailey & Lopez de Prado, 2014): the probability that the
observed Sharpe beats the best Sharpe you would expect from `trials`
variants with no skill, correcting for skew and fat tails.
"""

import itertools
import math
from dataclasses import dataclass, replace
from statistics import NormalDist

import numpy as np
import pandas as pd

from backend.factor import backtest
from backend.factor.model import Params

_N = NormalDist()
EULER_GAMMA = 0.5772156649


# Every variant ever tried, for the deflated Sharpe -- including the 8
# quarterly ones dropped from selection after the first run (2026-10-04):
# quarterly rebalancing checks the trend filter only once a quarter and
# rode the 2020 crash. Dropping them is a design fix, but they were tried,
# so they still raise the bar.
TRIALS_TRIED = 16


def grid(base: Params = Params()) -> list[Params]:
    """8 monthly variants: pure vs blended momentum, 15 vs 25 names, with and
    without vol targeting. Kept small on purpose: every extra variant raises
    the bar the deflated Sharpe sets."""
    return [
        replace(base, momentum_weight=w, top_n=n, buffer=n + 10, rebalance="monthly", target_vol=v)
        for w, n, v in itertools.product((1.0, 0.5), (15, 25), (None, 0.15))
    ]


def deflated_sharpe(returns: pd.Series, trial_sharpes: list[float]) -> float:
    """Probability (0..1) the strategy's Sharpe is real given how many
    variants were tried. Sharpes are per-period (daily), not annualised."""
    r = returns.dropna()
    t = len(r)
    if t < 30 or r.std() == 0:
        return 0.0
    sr = r.mean() / r.std()
    n = max(len(trial_sharpes), 1)
    var = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    sr0 = 0.0
    if n > 1 and var > 0:
        sr0 = math.sqrt(var) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))
    skew = float(r.skew())
    kurt = float(r.kurt()) + 3  # pandas reports excess kurtosis
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return 0.0
    return _N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


@dataclass
class WalkForward:
    returns: pd.Series            # stitched out-of-sample daily returns
    chosen: dict                  # test year -> Params chosen in-sample
    trials: dict                  # Params -> backtest.Result over the full period
    dsr: float

    def equity(self, capital: float = 1_000_000.0) -> pd.Series:
        return capital * (1 + self.returns).cumprod()


def walk_forward(closes: pd.DataFrame, market: pd.Series, start, end, variants: list[Params],
                 in_sample_years: int = 3) -> WalkForward:
    trials = {p: backtest.simulate(closes, market, p, start, end) for p in variants}
    daily = {p: r.equity.pct_change().fillna(0) for p, r in trials.items()}
    years = sorted({d.year for d in next(iter(daily.values())).index})
    pieces, chosen = [], {}
    for year in years[in_sample_years:]:
        def in_sample_sharpe(p):
            r = daily[p][(daily[p].index.year >= year - in_sample_years) & (daily[p].index.year < year)]
            return r.mean() / r.std() if r.std() else -np.inf
        best = max(variants, key=in_sample_sharpe)
        chosen[year] = best
        pieces.append(daily[best][daily[best].index.year == year])
    oos = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    trial_sharpes = [float(d.mean() / d.std()) for d in daily.values() if d.std()]
    # Pad to every variant ever tried with the spread observed, so dropped
    # variants keep counting against the deflated Sharpe.
    while 1 < len(trial_sharpes) < TRIALS_TRIED:
        trial_sharpes += trial_sharpes[: TRIALS_TRIED - len(trial_sharpes)]
    return WalkForward(returns=oos, chosen=chosen, trials=trials, dsr=deflated_sharpe(oos, trial_sharpes))
