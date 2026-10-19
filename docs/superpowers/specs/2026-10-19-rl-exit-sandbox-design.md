# RL exit-timing sandbox (Phase 21 step 6): design

Date: 2026-10-19. Status: approved in chat, awaiting spec review.
Source: `docs/ROADMAP.md` Phase 21 step 6 ("keep RL entirely isolated from live trading ...
require the same out-of-sample and paper gates"). Prior evidence: literature review (no
significant excess after costs) and the 2026-10-18 bandit test on 3,107 picks (lost to the fixed
rule; trailing stops lost every year).

## Decision (2026-10-19)

Retest RL honestly on one sequential decision: when to exit a Pick. Offline RL (fitted
Q-iteration with LightGBM; no torch, no GPU). Nothing is wired; a pass would lead to a later step
adding a paper-only `rl` forward-record source.

## Design

### `backend/rl/env.py`

- Episodes = Picks events: for each setup in `forecast/setups.py::SETUPS`, `forecast/study.py::events`
  over the `forecast/picks.py::load` table. Entry = next trading day's open (as `study.outcome`).
- `HMAX(setup) = 2 * setup.horizon`. On held day d = 1..HMAX the agent chooses `hold` or `exit`;
  the decision is taken at day d's close and `exit` fills at the OPEN of day d+1 (tradable); day HMAX
  forces exit. An episode needs bars through day HMAX+1, else it is dropped.
- State at day d (bars up to d only): `days_held / HMAX`, open P&L (close_d / entry − 1), NIFTY return since the entry open (nifty_close_d / nifty_open_entry − 1, so the state sees what the reward subtracts),
  20-day realised volatility, stock 20-day return − NIFTY 20-day return, NIFTY close / its 200-day
  mean − 1, setup one-hot.
- Reward on exit at d: `lab/assumptions.py::round_trip_return(entry, open_{d+1})` − NIFTY return over
  the same entry open → open_{d+1}. `fixed` (decide at day H) and `best_fixed` use the same fill.
- `episodes(t, setup) -> pd.DataFrame` long table: one row per (episode, day) with state columns,
  `exit_reward`, `next_row` index (None at HMAX), `episode_end` (date of day HMAX), `signal_date`.

### `backend/rl/agent.py`

- `fit(rows, iterations=5) -> Policy`: fitted Q-iteration. Q_exit(s) = `exit_reward` (known).
  Q_hold(s) regressed by LightGBM on target = max(Q_exit(s'), Q_hold(s')) for the next row
  (Q_hold at HMAX = −inf, i.e. forced exit). Same LightGBM params as `backend/ml/evaluate.py`,
  `num_threads=1`.
- `Policy.exit_day(episode_rows) -> int`: first d where Q_exit ≥ Q_hold.

### `backend/rl/evaluate.py`

- Folds: `lab/splits.py::yearly_folds(signal dates, min_train_years=3)`; train episodes need
  `episode_end < test_start`.
- Per test year, three exit rules on that year's episodes: `policy`, `fixed` (exit at the
  setup's horizon = today's rule), `best_fixed` (the holding period 1..HMAX with the best mean
  reward on the train episodes). Baseline = the better of `fixed` and `best_fixed` on train.
- Metrics per setup: mean excess per pick per rule, `improvement_by_year` (policy − baseline),
  `t` over yearly improvements (mean / (std/√n)), `hit_years` (share of years > 0), max drawdown
  of cumulative per-pick excess per rule, mean days held.
- `passes(result) -> (bool, reasons)`: mean improvement > 0 and t ≥ 2 and `hit_years` ≥ 0.70 and
  policy max drawdown ≤ baseline max drawdown, over at least `MIN_TEST_YEARS = 8` test years (fewer
  fails with "only N test years (< 8)").
- Family verdict: `run` returns/prints `family_passed = setups_passed >= 2` (one pass among five
  setups is not evidence) and stores `family_passed` and `setups_passed` in every row's metrics.
- `async run(db, now) -> dict`: one `lab_runs` row per setup, kind `rl`, name `fqi_exit:<setup>`,
  config (params, iterations, HMAX rule, features), `execution=DEFAULT`, window, fingerprint,
  folds, metrics + `passed` + `reasons` + caveats (today's universe list; price-only state).
  Records even on fail; reports `recorded <id>` / `NOT RECORDED`.
- CLI `python -m backend.rl.evaluate` (exit 1 only when a record fails or no bars).

### Isolation

- import-linter: `backend.rl` must not import `backend.routers`, `backend.autopilot`,
  `backend.engine`; nothing imports `backend.rl` except its own CLI.
- No schedule; admin runs it by hand in the jobs container with `nice`.

## Testing

- No look-ahead: changing bars after day d leaves the state at d unchanged.
- Fold purge: no train episode with `episode_end >= test_start`.
- Planted case: synthetic prices where every pick peaks on day 3 then decays → learned policy exits
  near day 3 and `passes` True.
- Noise prices → `passes` False with reasons.
- An always-hold-to-horizon policy reproduces the `fixed` rule's numbers exactly.
- `passes` boundaries (t 1.99, hit_years 0.69, drawdown worse by ε).
- `run` records one row per setup with kind `rl`, even on fail; payload `bson.encode`s.
- Synthetic test suite < 60 s in the image.

## Docs

Wiki `picks-and-signals.md` (RL sandbox), `platform.md` (import rule); handbook "RL exit sandbox"
section; `docs/ROADMAP.md` step 6 status with the first run's verdict.

## Out of scope

Wiring into Picks/AI/autopilot; sizing and execution RL; deep RL; online learning; options.
