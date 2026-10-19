# ML ranking harness (Phase 21 step 5): design

Date: 2026-10-19. Status: approved in chat, awaiting spec review.
Source: `docs/ROADMAP.md` Phase 21 step 5; plan doc "NeoTrade redesign" ML section ("What would
reopen ML" and its pass bar).

## Decision (2026-10-19)

Build a reproducible ML ranking harness on the Lab core and retest LightGBM honestly. Wire nothing
into Picks or the engine in this step. A model that passes the bar gets a separate follow-up step
(shadow `ml_rank`, rank/filter only, never sizing or exits, plus a forward-record source).

## Prerequisites (checked 2026-10-19)

| Prerequisite | Status |
|---|---|
| 10+ years of bars | yes: `daily_bars` 2009-01-02 to today, 236 symbols, 171 before 2012 |
| Point-in-time NIFTY 200 membership | no: today's list only; survivorship bias +4-8%/yr measured (`factor/survivorship.py`) |
| Features beyond price | no: `fundamentals` is a current snapshot |

The missing two are reported as a caveat on every run, not fixed here.

## Design

### `backend/ml/features.py` (moved from `forecast/research/ml_experiment_tool.py`)

- `features(t: dict) -> dict[str, pd.DataFrame]`: the tool's 24 price/volume features, wide frames
  (date × symbol), each using bars up to its own date only.
- `labels(t: dict, horizon: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]`: net forward
  return (entry t+1 open, exit close t+1+H, via `lab/assumptions.py::round_trip_return` with
  `DEFAULT`), NIFTY return over the same window, and the label end date per signal date.
- `long_table(f, t, horizon) -> pd.DataFrame`: one row per (date, symbol) every `STEP = 5`
  trading days, features + `net`, `nifty`, `excess`, `up`, `label_end`.
- Input `t` is `forecast/picks.py::load(db, now)`'s table (no pickle file).

### `backend/ml/evaluate.py`

- `HORIZONS = (20, 60)`; LightGBM `PARAMS` as in the tool (`n_jobs=4`, `random_state=0`).
- Per horizon, folds = `lab.splits.yearly_folds(dates, min_train_years=3, purge_days=horizon + 1)`;
  train rows are those whose `label_end` is before the test year starts.
- Per fold: `LGBMRegressor` on `excess` (ranker score) and `LGBMClassifier` on `up` (P(up)).
- Outputs per horizon:
  - `ic_by_year`: mean daily Spearman rank IC of the score vs `excess` per test year; `ic_t` over
    monthly means.
  - `brier`, `brier_base` (base rate = train-period P(up)), `brier_skill = 1 - brier / brier_base`.
  - `portfolio`: top decile by score every `STEP` days, equal weight, held `horizon` days,
    net of `round_trip_return` on every entry/exit (turnover counted); same construction for the
    `momentum_vol_60` score (`forecast/setups.py`) as the baseline; `excess_vs_momentum` =
    mean net per pick (model) − mean net per pick (momentum).
- `passes(result) -> tuple[bool, list[str]]`: True only if every test year's IC > 0, `ic_t > 2`,
  `excess_vs_momentum > 0`, and `brier_skill > 0`; the list names each failing condition.
- `async run(db, now, horizons=HORIZONS) -> dict`: loads the table, evaluates, records one
  `lab_runs` row per horizon (kind `ml`, name `lgbm_h<H>`, config = params + features + horizon,
  `execution = DEFAULT`, window, fingerprint of the close table, folds, metrics = outputs above +
  `passed` + `reasons` + `caveats` = the two missing prerequisites).
- CLI `python -m backend.ml.evaluate [--horizon 20]` (prints the verdict per horizon; exit 0
  always). Launched by an admin by hand inside the jobs container with `nice`; no schedule.

### Housekeeping

- `backend/requirements.txt`: `lightgbm==4.6.0` (aarch64 wheel 3.4 MB; no scikit-learn: metrics
  via numpy/scipy).
- Delete `backend/forecast/research/ml_experiment_tool.py` (superseded). Bandit tool unchanged.
- `lab/__main__.py rerun`: `ml` stays "not re-runnable here" (exit 2) — reruns take minutes; the
  CLI is the rerun.
- import-linter: `backend.ml` must not import `backend.routers`, `backend.autopilot`,
  `backend.engine`; nothing in the app imports `backend.ml` except its own CLI.

## Testing

- Synthetic table (40 symbols × 8 years, planted signal: one feature predicts next-20-day excess)
  → every year IC > 0, `passes` True.
- Pure noise table → `passes` False with an IC reason.
- No look-ahead: changing bars after date d does not change features at d.
- Purge: no train row has `label_end` ≥ test start.
- `passes` boundaries: one year IC ≤ 0 → False; `ic_t` 1.99 → False; `brier_skill` 0 → False.
- `run` records one `lab_runs` row per horizon with kind `ml`.
- Runtime guard: the synthetic test finishes in under 60 s in the image.

## Docs

`docs/wiki/picks-and-signals.md` (ML harness, research tool removed), `platform.md` (requirements,
import rule); handbook "ML ranking" section with the bar and how to run it; `docs/ROADMAP.md` step 5
status with the first real run's verdict.

## Out of scope

Wiring a model into Picks/engine, point-in-time membership, fundamentals history, intraday ML,
deep learning, scheduling the evaluation.
