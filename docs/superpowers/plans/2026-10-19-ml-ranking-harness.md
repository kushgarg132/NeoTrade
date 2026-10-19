# ML ranking harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reproducible LightGBM ranking evaluation on the Lab core that checks the redesign doc's pass bar against the momentum baseline and records the verdict in `lab_runs`.

**Architecture:** `backend/ml/features.py` (pure feature/label tables, moved from the research tool) and `backend/ml/evaluate.py` (folds, models, metrics, `passes`, `run`, CLI). Nothing in the app imports `backend.ml`.

**Tech Stack:** Python 3.11 prod image, pandas/numpy/scipy, `lightgbm==4.6.0`.

**Spec:** `docs/superpowers/specs/2026-10-19-ml-ranking-harness-design.md`

## Global Constraints

- `HORIZONS = (20, 60)`, `STEP = 5`, folds `yearly_folds(dates, min_train_years=3, purge_days=horizon + 1)`; train rows need `label_end < test_start`.
- Returns via `lab/assumptions.py::round_trip_return` with `DEFAULT` (10 bps + CNC charges); NIFTY over the identical window.
- Pass bar: every test year IC > 0, `ic_t > 2`, `excess_vs_momentum > 0`, `brier_skill > 0`.
- `lab_runs` rows: kind `ml`, name `lgbm_h<H>`, `caveats` = ["no point-in-time NIFTY 200 membership (survivorship +4-8%/yr)", "price/volume features only (no fundamentals history)"].
- No scikit-learn. LightGBM `n_jobs=4`, `random_state=0`.
- Backend gate: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify sh -c "python -m pytest -q backend/tests; lint-imports --config backend/.importlinter"` (Python 3.11: no PEP 701 nested-quote f-strings).
- Wiki section + `verified_at` in the same commit. Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Look-ahead: a feature at date d computed from bars after d would fake a pass — Task 1 test mutates later bars and asserts features at d are unchanged.
- Overlap leakage: a train label ending inside the test year — Task 2 test asserts none.
- Momentum baseline built with different turnover/costs than the model — Task 2 test: identical scores give `excess_vs_momentum == 0`.
- A run on the real table must not exhaust the VM (4 cores, ~23 GB): `STEP = 5` sampling; document expected runtime in the handbook after the first real run.
- `run` must record even when `passes` is False (the verdict is the point).

---

### Task 1: Features and labels

**Files:**
- Create: `backend/ml/__init__.py`, `backend/ml/features.py`, `backend/tests/test_ml_features.py`
- Delete: `backend/forecast/research/ml_experiment_tool.py`
- Modify: `backend/requirements.txt` (`lightgbm==4.6.0  # ML ranking harness (backend/ml/), aarch64 wheel; no scikit-learn`)

**Interfaces:**
- Produces: `FEATURES: list[str]` (24 names), `features(t: dict) -> dict[str, pd.DataFrame]`, `labels(t: dict, horizon: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]` (net, nifty, label_end by signal date), `long_table(f: dict, t: dict, horizon: int, step: int = 5) -> pd.DataFrame` columns `date, symbol, *FEATURES, net, nifty, excess, up, label_end`.

- [ ] **Step 1: Failing tests:** `features` returns all 24 names; mutating `t` closes after date d leaves every feature row ≤ d unchanged; `labels` net for one symbol equals `round_trip_return(open[t+1], close[t+1+H])`; `long_table` rows every 5th date, no NaN labels, `excess == net - nifty`, `up == (net > 0)`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Move the tool's `features`, `labels`, `long_table` (use `DEFAULT`, not `NO_SLIP`), drop pickle loading; delete the tool. **Step 4:** Image rebuilt; suite green.
- [ ] **Step 5:** Commit `feat(ml): feature and label tables for the ML harness`.

### Task 2: Evaluation, pass bar, run record, CLI

**Files:**
- Create: `backend/ml/evaluate.py`, `backend/ml/__main__.py` (or `if __name__ == "__main__"` in evaluate.py; CLI `python -m backend.ml.evaluate`), `backend/tests/test_ml_evaluate.py`
- Modify: `backend/.importlinter` (contract: `backend.ml` must not import `backend.routers`, `backend.autopilot`, `backend.engine`; app modules must not import `backend.ml`)

**Interfaces:**
- Consumes: Task 1 functions; `lab.splits.yearly_folds`; `lab.runs.LabRunStore`, `fingerprint`; `forecast.picks.load`; `forecast.setups` momentum_vol_60 score.
- Produces: `evaluate(t: dict, horizon: int) -> dict` keys `ic_by_year: dict[int, float]`, `ic_t: float | None`, `brier, brier_base, brier_skill`, `portfolio: {model, momentum, excess_vs_momentum}`, `folds: list[Fold]`; `passes(result: dict) -> tuple[bool, list[str]]`; `async run(db, now, horizons=HORIZONS) -> dict[int, dict]`.

- [ ] **Step 1: Failing tests:**
  - planted-signal synthetic table (40 symbols × 8 years; feature `mom_20` drives next-20-day excess) → every `ic_by_year` > 0 and `passes(...)[0] is True`;
  - noise table → `passes` False and reasons mention IC;
  - no train row with `label_end >= test_start` in any fold;
  - `passes` boundaries: one year IC = 0 → False; `ic_t = 1.99` → False; `brier_skill = 0` → False; reasons list each failing condition;
  - portfolio with model score identical to the momentum score → `excess_vs_momentum == 0`;
  - `run` with a fake db/`LabRunStore` records one row per horizon with kind `ml`, `passed`, `reasons`, `caveats`, even when not passed;
  - the planted-signal test completes in < 60 s.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (Spearman via `scipy.stats.spearmanr` per date; `ic_t` = mean / (std/√n) over monthly mean ICs; Brier base = train-period mean of `up`). **Step 4:** Suite + lint green.
- [ ] **Step 5:** Wiki `picks-and-signals.md` (ML harness, tool removed), `platform.md` (requirements, import rule); handbook "ML ranking" section (bar, how to run: `docker exec neotrade-jobs nice python -m backend.ml.evaluate`); commit `feat(ml): evaluation harness with the pass bar, recorded in lab_runs`.

---

## Ship

- [ ] Merge, gate, final review (one fix wave), deploy direct outside 15:30-17:00 IST.
- [ ] Run `docker exec neotrade-jobs nice python -m backend.ml.evaluate` once; record the verdict in `docs/ROADMAP.md` step 5 status and in the handbook.
