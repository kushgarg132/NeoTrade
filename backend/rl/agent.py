"""Fitted Q-iteration for the exit decision, LightGBM as the regressor.

Q_exit(s) is the row's `exit_reward` (known: decide at the close, fill at the next open). Q_hold(s) is regressed on the NEXT row of the same
episode only: target = max(Q_exit(s'), Q_hold(s')), and Q_hold at the last day is -inf (a forced
exit), so a row never sees its own reward in its target. After k iterations the policy looks about
k days ahead. The policy exits on the first day Q_exit >= Q_hold, or on the last day.
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.rl.env import STATE

# as backend/ml/evaluate.py::PARAMS: lightgbm's native API (no scikit-learn in production), 1 thread
# (4 were ~25x slower on this shared 4-core host)
PARAMS = dict(learning_rate=0.03, num_leaves=31, min_data_in_leaf=200, bagging_fraction=0.8, bagging_freq=1,
              feature_fraction=0.8, num_threads=1, verbose=-1, seed=0, objective="regression")
ROUNDS = 100  # x5 iterations x ~14 folds on ~10^6 rows per setup; 300 (the ML harness) is ~3x the run time


def _train(X: pd.DataFrame, y: np.ndarray):
    return lgb.train(PARAMS, lgb.Dataset(X, y), ROUNDS)


class Policy:
    def __init__(self, model):
        self.model = model

    def q_hold(self, rows: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.model.predict(rows[STATE]), dtype=float)

    def exit_days(self, rows: pd.DataFrame) -> pd.Series:
        """episode -> the day it exits: first day Q_exit >= Q_hold, the last day at the latest."""
        go = (rows["exit_reward"].to_numpy() >= self.q_hold(rows)) | (rows["next_row"].to_numpy() < 0)
        return rows.loc[go].groupby("episode")["day"].min()


def fit(rows: pd.DataFrame, iterations: int = 5, train=_train) -> Policy:
    """`rows` as `env.episodes` (next_row = position in this table, -1 on the last day).
    `train(X, y)` returns an object with `predict(X)`; replaceable for tests."""
    X, reward = rows[STATE], rows["exit_reward"].to_numpy()
    nxt_all = rows["next_row"].to_numpy()
    has_next = nxt_all >= 0
    nxt = nxt_all[has_next]
    model = None
    for _ in range(iterations):
        target = reward[nxt]  # Q_exit(s'), and Q_hold(s') once there is a model
        if model is not None:
            hold = np.asarray(model.predict(X), dtype=float)[nxt]
            hold[nxt_all[nxt] < 0] = -np.inf  # the model never saw last-day states: Q_hold there is -inf
            target = np.maximum(target, hold)
        model = train(X[has_next], target)
    return Policy(model)
