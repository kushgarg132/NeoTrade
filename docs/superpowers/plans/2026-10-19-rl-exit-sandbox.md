# RL exit-timing sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An isolated offline-RL (fitted Q-iteration) exit-timing evaluation on Picks episodes, compared with fixed-horizon baselines under a pass bar, recorded in `lab_runs`.

**Architecture:** `backend/rl/env.py` (episode/state table), `agent.py` (FQI with LightGBM, policy), `evaluate.py` (folds, baselines, metrics, `passes`, `run`, CLI). Nothing in the app imports `backend.rl`.

**Tech Stack:** Python 3.11 prod image, pandas/numpy, `lightgbm==4.6.0` (installed).

**Spec:** `docs/superpowers/specs/2026-10-19-rl-exit-sandbox-design.md`

## Global Constraints

- `HMAX = 2 * setup.horizon`; exit at day d's close; forced exit at HMAX.
- Reward = `lab/assumptions.py::round_trip_return(entry, close_d)` (DEFAULT) − NIFTY return over the same entry/exit days.
- FQI iterations = 5; LightGBM params as `backend/ml/evaluate.py` with `num_threads=1`; no scikit-learn.
- Folds `yearly_folds(signal_dates, min_train_years=3)`; train episodes need `episode_end < test_start`.
- Pass bar: mean improvement > 0 AND t ≥ 2 over yearly improvements AND `hit_years` ≥ 0.70 AND policy max drawdown ≤ baseline max drawdown.
- `lab_runs`: kind `rl`, name `fqi_exit:<setup>`, caveats ["no point-in-time NIFTY 200 membership (survivorship +4-8%/yr)", "price-only state"]; record even on fail; dict keys str; `bson.encode`-safe.
- Import contract: `backend.rl` must not import `backend.routers`, `backend.autopilot`, `backend.engine`; app modules must not import `backend.rl`.
- Backend gate: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify sh -c "python -m pytest -q backend/tests; lint-imports --config backend/.importlinter"` (Python 3.11: no PEP 701 nested-quote f-strings).
- Wiki section + `verified_at` in the same commit; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Look-ahead in the state (rolling windows, NIFTY trend) — Task 1 mutation test.
- Q_hold target built from the same row (leak) instead of the next row — Task 2 test on a hand-built 3-day episode.
- Baseline chosen on test data — Task 3 test: `best_fixed` uses train episodes only.
- Always-hold policy must equal `fixed` exactly — Task 3 test.
- Run records even when failing and reports NOT RECORDED.

---

### Task 1: Episodes and state

**Files:** Create `backend/rl/__init__.py`, `backend/rl/env.py`, `backend/tests/test_rl_env.py`.

**Interfaces:** Produces `STATE: list[str]`, `hmax(setup) -> int`, `episodes(t: dict, setup) -> pd.DataFrame` with columns `episode`, `signal_date`, `day` (1..HMAX), `*STATE`, `exit_reward`, `next_row` (int row position or -1 at HMAX), `episode_end`.

- [ ] **Step 1: Failing tests:** state at day d unchanged when bars after d change; `exit_reward` for one row equals `round_trip_return(open[entry], close[d]) - nifty_ret`; `next_row` points to day d+1 of the same episode, -1 at HMAX; an episode whose bars run out before HMAX is truncated with its last available day forced exit (or dropped — choose drop and test it).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement using `study.events` for episode starts. **Step 4:** Suite green. **Step 5:** Commit `feat(rl): Picks exit episodes and state`.

### Task 2: Fitted Q-iteration agent

**Files:** Create `backend/rl/agent.py`, `backend/tests/test_rl_agent.py`.

**Interfaces:** Consumes Task 1 table. Produces `PARAMS`, `fit(rows: pd.DataFrame, iterations: int = 5) -> Policy`; `Policy.q_hold(rows) -> np.ndarray`; `Policy.exit_days(rows) -> pd.Series` (episode → chosen exit day).

- [ ] **Step 1: Failing tests:** on a hand-built table where rewards are [0.01, 0.05, 0.02] for days 1-3 across many identical episodes, the policy exits on day 2; Q_hold regression target for a row uses only its `next_row` (assert via a tiny table and a stub regressor); forced exit at HMAX.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement with `lgb.train` (regression). **Step 4:** Suite green. **Step 5:** Commit `feat(rl): fitted Q-iteration exit agent`.

### Task 3: Evaluation, pass bar, run record, CLI

**Files:** Create `backend/rl/evaluate.py`, `backend/tests/test_rl_evaluate.py`; Modify `backend/.importlinter`.

**Interfaces:** Consumes Tasks 1-2, `lab.splits.yearly_folds`, `lab.runs.LabRunStore`, `fingerprint`, `forecast.picks.load`, `forecast.setups.SETUPS`. Produces `evaluate(t, setup) -> dict` (keys: `rules{policy,fixed,best_fixed}` each `{mean_excess, max_drawdown, mean_days}`, `baseline`, `improvement_by_year` (str year keys), `t`, `hit_years`, `folds`), `passes(result) -> (bool, list[str])`, `async run(db, now) -> dict`, CLI `python -m backend.rl.evaluate`.

- [ ] **Step 1: Failing tests:** planted synthetic prices (picks peak day 3, decay after) → policy mean days ≈ 3 and `passes` True; noise → False with reasons; always-hold policy (inject) equals `fixed` exactly; `best_fixed` chosen from train only (test where test-year best differs); `passes` boundaries (t 1.99, hit 0.69, drawdown worse); `run` with a fake store records one row per setup with kind `rl` even on fail, prints NOT RECORDED when record returns None; payload `bson.encode`s; suite < 60 s.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Suite + lint green.
- [ ] **Step 5:** Wiki `picks-and-signals.md`, `platform.md`; handbook "RL exit sandbox" (how to run: `docker exec neotrade-jobs nice python -m backend.rl.evaluate`); commit `feat(rl): exit sandbox evaluation with the pass bar, recorded in lab_runs`.

---

## Ship

- [ ] Merge, gate, final review, one fix wave; deploy direct outside 15:30-17:00 IST.
- [ ] Run the CLI once; write the verdict into `docs/ROADMAP.md` step 6 and the handbook; if Phase 21 steps 1-6 are all done, set Phase 21 status done.
