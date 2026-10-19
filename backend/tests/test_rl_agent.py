"""backend.rl.agent: fitted Q-iteration targets, the learned exit day, the forced exit."""

import numpy as np
import pandas as pd

from backend.rl import agent
from backend.rl.env import STATE


def _table(rewards, episodes) -> pd.DataFrame:
    """`episodes` identical episodes whose day d pays rewards[d-1]; states differ only by `held`."""
    h = len(rewards)
    n = episodes * h
    out = pd.DataFrame(0.0, index=range(n), columns=STATE)
    out["episode"] = np.repeat(np.arange(episodes), h)
    out["day"] = np.tile(np.arange(1, h + 1), episodes)
    out["held"] = out["day"] / h
    out["exit_reward"] = np.tile(rewards, episodes)
    out["next_row"] = np.where(out["day"] == h, -1, np.arange(n) + 1)
    return out


def test_policy_exits_on_the_peak_day():
    rows = _table([0.01, 0.05, 0.02], 400)
    pol = agent.fit(rows)
    assert set(pol.exit_days(rows)) == {2} and len(pol.exit_days(rows)) == 400


class Stub:
    """A regressor that records what it was fitted on and predicts 10 * held."""
    fits: list

    def __init__(self, X, y):
        self.fits = []

    def predict(self, X):
        return 10 * X["held"].to_numpy()


def test_q_target_uses_only_the_next_row():
    rows = _table([0.1, 0.2, 0.3], 1)
    rows["exit_reward"] = [1.0, 2.0, 3.0]
    fits = []

    def train(X, y):
        fits.append((X.copy(), np.array(y)))
        return Stub(X, y)

    agent.fit(rows, iterations=2, train=train)
    (X1, y1), (X2, y2) = fits
    assert len(X1) == 2 and X1["held"].tolist() == [1 / 3, 2 / 3]  # the last day has no target
    assert y1.tolist() == [2.0, 3.0]  # first pass: Q_exit of the NEXT row, never the row's own 1.0 / 2.0
    # second pass: max(Q_exit(next), Q_hold(next)); the stub's Q_hold is 10 * held of the next row, except
    # on the last day, where Q_hold is -inf (forced exit), so the penultimate target is the exit value alone
    assert np.allclose(y2, [max(2.0, 10 * 2 / 3), 3.0])


def test_last_day_is_a_forced_exit_whatever_q_hold_says():
    rows = _table([0.01, 0.05, 0.02], 3)
    pol = agent.Policy(Stub(None, None))  # Q_hold = 10 * held > every reward: always hold
    assert pol.exit_days(rows).tolist() == [3, 3, 3]
