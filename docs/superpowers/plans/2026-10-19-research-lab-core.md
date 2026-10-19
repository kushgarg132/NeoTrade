# Research Lab core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared `backend/lab/` core (execution assumptions, walk-forward folds, metrics, stored runs) that the engine, factor and Picks-study simulators all use, plus an admin Runs view.

**Architecture:** Pure modules in `backend/lab/` with no I/O except `runs.py` (Mongo). Simulators import from `lab` instead of owning constants. Runs are recorded best-effort at each simulator entry point. A CLI re-runs factor and study runs from stored config.

**Tech Stack:** Python 3.11 (prod image), pandas/numpy, `empyrical-reloaded==0.7.0`, FastAPI + Motor; React 19 frontend (`node:test`).

**Spec:** `docs/superpowers/specs/2026-10-19-research-lab-core-design.md`

## Global Constraints

- Default execution: `slippage_bps = 10.0`, engine `fill = "next_open"`, factor `fill = "next_close"`.
- Charges come only from `engine/execution/costs.py::calculate_indian_costs`; never duplicated.
- Backtest gate thresholds and `engine/metrics.py` stay unchanged (`MIN_WINDOW_DAYS=365`, `MIN_TRADES=30`, `MIN_PROFIT_FACTOR=1.3`, `MAX_DRAWDOWN=0.15`).
- `LabRunStore.record` never raises into a simulator (log a warning).
- `/lab/runs` API and page are admin only.
- Backend gate: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify python -m pytest -q backend/tests` (Python 3.11: no PEP 701 nested-quote f-strings). Import lint: `lint-imports --config backend/.importlinter` inside the image.
- Frontend: `cd frontend && node --test $(find src -name '*.test.js')` and `npm run build`.
- Each code change updates its `docs/wiki/*` page section and `verified_at` in the same commit (`python3 docs/wiki/stale.py`).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings narrowing the spec (made while planning)

- `learning/retune.py` and `builder/draft.py` keep their single in-sample/hold-out split; they do NOT adopt `yearly_folds` (it would change which params/drafts pass). They only record runs and take slippage from `lab`.
- The two research tools (`forecast/research/*_tool.py`) are not changed: they need lightgbm, which the image and tests lack.
- Study runs record event stats (`study.stats` + walk-forward), not `summary` (no daily return series exists for an event study).
- `retune._daily` moves to `lab/metrics.py::daily_returns` (retune and builder import it from there).

## Review Focus

- Engine backtest P&L unchanged after the refactor (same 10 bps, same fills): pinned by existing `test_backtest_*` staying green without edits.
- Factor walk-forward result identical with purge 0: Task 2 pins `chosen` years and OOS return sum on a fixture before/after.
- Picks study now slipped: `net_return` for entry 100 exit 110 drops by the slippage amount; Task 1 asserts the exact value.
- `record` failure (Mongo down) does not fail a gate backtest or the 16:00 Picks pass: Task 4 test with a store that raises.
- Non-admin `GET /api/v1/lab/runs` returns 403: Task 6 test.

---

## Wave 1 (parallel: Tasks 1, 2, 3)

### Task 1: Execution assumptions

**Files:**
- Create: `backend/lab/__init__.py`, `backend/lab/assumptions.py`, `backend/tests/test_lab_assumptions.py`, `backend/tests/test_lab_single_source.py`
- Modify: `backend/engine/backtest.py:32-33,56`, `backend/factor/backtest.py:28,70,100-112`, `backend/forecast/study.py:24-27`, `backend/builder/draft.py:29,286`

**Interfaces:**
- Produces: `Execution(slippage_bps: float = 10.0, fill: Literal["next_open","next_close"] = "next_open")` (frozen dataclass), `DEFAULT = Execution()`, `DAILY = Execution(fill="next_close")`, `fill_price(price: float, side: Side, ex: Execution) -> float`, `round_trip_return(entry: float, exit_: float, ex: Execution = DEFAULT, notional: float = 1e5, product: str = "CNC") -> float`.

- [ ] **Step 1: Write failing tests** `test_lab_assumptions.py`

```python
def test_fill_price_is_adverse():
    assert fill_price(100.0, Side.BUY, DEFAULT) == pytest.approx(100.1)
    assert fill_price(100.0, Side.SELL, DEFAULT) == pytest.approx(99.9)

def test_round_trip_matches_hand_math():
    qty = 1e5 / 100.1
    charges = calculate_indian_costs(100.1, qty, Side.BUY, "CNC") + calculate_indian_costs(109.89, qty, Side.SELL, "CNC")
    assert round_trip_return(100.0, 110.0) == pytest.approx((qty * (109.89 - 100.1) - charges) / 1e5)

def test_study_net_return_uses_it():
    assert study.net_return(100.0, 110.0) == pytest.approx(round_trip_return(100.0, 110.0))

def test_factor_trade_and_engine_client_slip_the_same():
    # one stock, full weight, factor _trade buy fill price == fill_price(..., BUY, DAILY)
    # SimulatedExecutionClient built by engine.backtest uses DEFAULT.slippage_bps
    ...
```

`test_lab_single_source.py`: walk `backend/**/*.py` (skip `backend/lab/`, `backend/tests/`); fail on any line matching `r"SLIPPAGE_BPS\s*="` or `r"slippage_bps\s*=\s*\d"`.

Fill in the factor/engine parity body: call `factor.backtest._trade` with one symbol and weight 1.0 and read the cash spent; assert the implied price equals `fill_price(price, Side.BUY, DAILY)`. For the engine, assert `engine.backtest` constructs the client with `slippage_bps == DEFAULT.slippage_bps` (monkeypatch `SimulatedExecutionClient` to capture kwargs).

- [ ] **Step 2:** Run them in the image → FAIL.
- [ ] **Step 3:** Implement `lab/assumptions.py`. `study.net_return` becomes a call to `round_trip_return`; `factor/backtest.py` drops `SLIPPAGE_BPS`, `simulate(..., ex: Execution = DAILY)` and `_trade(..., ex: Execution, ...)` use `fill_price`; `engine/backtest.py` drops `BACKTEST_SLIPPAGE_BPS`, passes `slippage_bps=DEFAULT.slippage_bps`; `builder/draft.py:286` uses `DEFAULT.slippage_bps`.
- [ ] **Step 4:** Full in-image suite. Update only Picks/study tests whose expected returns change because of slippage (state each changed number in the commit body). Engine and factor tests must pass unedited.
- [ ] **Step 5:** Wiki: `trading-engine.md` (backtest slippage now from `lab.assumptions`), `picks-and-signals.md` (study net return slipped; factor slippage source). Handbook Picks caveat line about slippage. Commit `feat(lab): one execution-assumptions source for every simulator`.

### Task 2: Walk-forward folds

**Files:**
- Create: `backend/lab/splits.py`, `backend/tests/test_lab_splits.py`
- Modify: `backend/factor/validate.py:80-110`, `backend/forecast/study.py:82-112`

**Interfaces:**
- Produces: `Fold(year: int, train_start: date, train_end: date, test_start: date, test_end: date)` (frozen dataclass; ends exclusive), `yearly_folds(dates: Sequence[date], min_train_years: int, window_years: int | None = None, purge_days: int = 0, embargo_days: int = 0) -> list[Fold]` — one fold per calendar year after the first `min_train_years` years; train = `[test_start - window_years, test_start)` (or from the first date when `window_years` is None), minus the last `purge_days` trading days (from `dates`), minus any days within `embargo_days` trading days after an earlier test year's end.

- [ ] **Step 1: Write failing tests**

```python
def test_rolling_three_year_window():
    days = pd.bdate_range("2010-01-01", "2015-12-31").date
    f = yearly_folds(days, min_train_years=3, window_years=3)
    assert [x.year for x in f] == [2013, 2014, 2015]
    assert f[0].train_start == date(2010, 1, 1) and f[0].test_start == date(2013, 1, 1)

def test_purge_drops_trading_days_before_test():
    days = pd.bdate_range("2010-01-01", "2012-12-31").date
    f = yearly_folds(days, min_train_years=2, purge_days=5)[0]
    assert f.train_end == days[list(days).index(date(2012, 1, 2)) - 5]

def test_too_little_history_gives_no_folds():
    assert yearly_folds(pd.bdate_range("2020-01-01", "2020-12-31").date, min_train_years=3) == []

def test_factor_walk_forward_unchanged(fixture_closes):
    # fixture: 6 years synthetic closes for 40 symbols + market, 2 variants; compare
    # chosen years and round(sum(oos returns), 10) to values captured from the pre-change code
    ...
```

Capture the factor fixture's expected `chosen` and OOS sum by running the CURRENT `walk_forward` before editing it, and hard-code them in the test. Same for `study.walk_forward` on a small synthetic events frame (expected `years` list and `brier`).

- [ ] **Step 2:** Run → FAIL (module missing).
- [ ] **Step 3:** Implement `splits.py`. `factor/validate.py::walk_forward` iterates `yearly_folds(index, min_train_years=in_sample_years, window_years=in_sample_years)` and slices by fold dates. `study.walk_forward` iterates `yearly_folds(signal dates, min_train_years=0)` for years and keeps its `exit < test_start` event filter (that is its purge) and `MIN_PRIOR` check.
- [ ] **Step 4:** Tests PASS; full suite green.
- [ ] **Step 5:** Wiki `picks-and-signals.md` (both walk-forwards use `lab.splits`). Commit `feat(lab): shared purged walk-forward folds`.

### Task 3: Metrics

**Files:**
- Create: `backend/lab/metrics.py`, `backend/tests/test_lab_metrics.py`
- Modify: `backend/requirements.txt` (add `empyrical-reloaded==0.7.0  # Apache-2.0, standard return metrics (backend/lab/metrics.py)`), `backend/learning/retune.py:49-58` (move `_daily`), `backend/builder/draft.py:33`, `backend/factor/backtest.py::performance`

**Interfaces:**
- Produces: `summary(daily_returns: pd.Series, benchmark: pd.Series | None = None) -> dict` keys `cagr, sharpe, sortino, max_drawdown, volatility, alpha, beta` (floats or None); `daily_returns(trades: list[dict], start: datetime, end: datetime, account: float) -> pd.Series` (the old `retune._daily` with `account` explicit; retune passes `ACCOUNT`).

- [ ] **Step 1: Write failing tests**

```python
def test_summary_matches_empyrical():
    r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 500), index=pd.bdate_range("2024-01-01", periods=500))
    s = summary(r)
    assert s["sharpe"] == pytest.approx(empyrical.sharpe_ratio(r))
    assert s["max_drawdown"] == pytest.approx(empyrical.max_drawdown(r))
    assert s["alpha"] is None and s["beta"] is None

def test_summary_short_series_is_all_none():
    assert set(summary(pd.Series([0.01])).values()) == {None}

def test_daily_returns_same_as_old_retune(...):  # one trade on a weekday -> pnl/account on that day, 0 elsewhere
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; NaN/inf from empyrical → None. `factor/backtest.py::performance` adds `"summary": summary(returns)` (existing keys unchanged). Retune/builder import `daily_returns` and keep `_sharpe`.
- [ ] **Step 4:** Image rebuilt (new dependency); full suite green.
- [ ] **Step 5:** Wiki `picks-and-signals.md` (retune `_daily` moved), `platform.md` (requirements). Commit `feat(lab): standard metrics via empyrical-reloaded`.

---

## Wave 2

### Task 4: Run records

**Files:**
- Create: `backend/lab/runs.py`, `backend/tests/test_lab_runs.py`
- Modify: `backend/server.py` (ensure indexes at startup), `backend/risk/gate_backtest.py:110`, `backend/factor/report.py::run`, `backend/forecast/picks.py::run`, `backend/learning/retune.py::retune_strategy` caller in `run_all`, `backend/builder/draft.py::_test`, `backend/.importlinter`

**Interfaces:**
- Consumes: `Execution` (T1), `Fold` (T2), `summary`, `daily_returns` (T3).
- Produces: `COLLECTION = "lab_runs"`; `fingerprint(frame: pd.DataFrame) -> str` (sha256 over symbols sorted, dates, closes rounded to 4 dp; column order independent); `LabRunStore(db)` with `async ensure_indexes()`, `async record(*, kind: str, name: str, config: dict, execution: Execution, window: tuple[date, date], fingerprint: str | None, folds: list[Fold], metrics: dict, user_id: str = "system") -> str | None` (returns id, or None after logging when the insert fails), `async get(run_id: str) -> dict | None`, `async list(kind: str | None = None, name: str | None = None, limit: int = 50) -> list[dict]` (newest first). `code_sha()` = env `GIT_SHA`, else `git rev-parse HEAD`, else `"unknown"`.

- [ ] **Step 1: Write failing tests** (use the repo's existing in-memory Mongo fake from other store tests)

```python
async def test_record_then_get_round_trips(fake_db): ...
def test_fingerprint_ignores_column_order_and_sees_one_close():
    a = pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]}, index=pd.bdate_range("2024-01-01", periods=2))
    assert fingerprint(a) == fingerprint(a[["Y", "X"]])
    b = a.copy(); b.iloc[1, 0] = 2.0001
    assert fingerprint(a) != fingerprint(b)
async def test_record_failure_never_raises(broken_db):
    assert await LabRunStore(broken_db).record(kind="factor", name="x", config={}, execution=DEFAULT,
                                               window=(date(2020,1,1), date(2021,1,1)), fingerprint=None,
                                               folds=[], metrics={}) is None
async def test_gate_backtest_still_returns_when_record_fails(...): ...
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `runs.py`. Writers:
  - gate backtest: kind `engine`, name = strategy, metrics = `{**gate fields (trades, pf, dd, net), "summary": summary(daily_returns(result.trades, start, end, account_size))}`, fingerprint None (bars not kept), user_id = the admin.
  - factor report `run`: kind `factor`, config `{"start", "end", "variants": [asdict(p) ...]}`, fingerprint of `closes`, folds from T2, metrics = strategy performance.
  - Picks `run`: one record per setup, kind `study`, name = setup, config `{"horizon"}`, fingerprint of the bar table `t`'s close frame, metrics = the setup's stats + walk_forward.
  - retune `run_all`: kind `engine`, name `retune:<strategy>`, metrics = the returned doc's train summary + accepted.
  - builder `_test`: kind `engine`, name `builder:<slug>`, metrics = `fields["metrics"]` + sharpe.
  - `.importlinter`: new forbidden contract, `backend.lab` must not import `backend.routers` or `backend.autopilot`.
- [ ] **Step 4:** Full suite + lint green.
- [ ] **Step 5:** Wiki: `picks-and-signals.md` (Data: `lab_runs`), `platform.md` (startup indexes, import rule). Commit `feat(lab): every simulator records a reproducible run`.

---

## Wave 3 (parallel: Tasks 5, 6)

### Task 5: Re-run CLI

**Files:**
- Create: `backend/lab/__main__.py`, `backend/tests/test_lab_rerun.py`

**Interfaces:**
- Consumes: `LabRunStore`, `fingerprint` (T4).
- Produces: `python -m backend.lab rerun <id>`; `async rerun(db, run_id, sources=None) -> tuple[int, dict]` (exit code, report with `fingerprint_then`, `fingerprint_now`, `deltas`). Exit 0 = same fingerprint and every metric within 1e-6; 1 = differs; 2 = kind not re-runnable here (`engine`, `ml`, `bandit`, message "not re-runnable here").

- [ ] **Step 1: Failing tests:** stored factor run on a fixture `sources` (closes + market callables) → exit 0; same run with one close changed → exit 1 and fingerprints differ; `engine` run → exit 2.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (factor: `factor.report.run(start, end)` path with injectable data; study: `forecast.picks.compute` over the stored setup). **Step 4:** PASS + suite.
- [ ] **Step 5:** Handbook page section "Reproducing a run"; commit `feat(lab): rerun a stored run`.

### Task 6: Runs API and Lab tab

**Files:**
- Create: `backend/routers/lab.py`, `backend/tests/test_lab_api.py`, `frontend/src/pages/LabRuns.jsx`, `frontend/src/utils/labRuns.js`, `frontend/src/utils/labRuns.test.js`
- Modify: `backend/server.py` (mount router), `frontend/src/App.jsx` (`/lab/runs` in `RequireAdmin`), `frontend/src/components/layout/sections.js` (`LAB_TABS` add Runs `/lab/runs`), `frontend/src/utils/routes.js` (`ROUTES`, `ADMIN_ROUTES`), `frontend/src/utils/api.js` (endpoints)

**Interfaces:**
- Consumes: `LabRunStore` (T4).
- Produces: `GET /api/v1/lab/runs?kind=&name=&limit=` → `{"runs": [...]}` without `folds`; `GET /api/v1/lab/runs/{id}` → full run, 404 when missing; both `require_admin`. Frontend `compareRows(a, b) -> [{key, a, b}]` over `cagr, sharpe, sortino, max_drawdown, volatility, alpha, beta` plus kind-specific numeric keys present in both.

- [ ] **Step 1: Failing tests:** API — admin lists newest first and filters by kind; non-admin 403; unknown id 404. Frontend — `compareRows` returns the 7 summary keys in order and skips a key missing from one side.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. Page: table (created, kind, name, window, code SHA short, CAGR, Sharpe, max DD), two checkboxes enable "Compare" → side-by-side table from `compareRows`. `SectionTabs tabs={LAB_TABS} label="Lab"`.
- [ ] **Step 4:** Backend suite, node tests, build.
- [ ] **Step 5:** Wiki `platform.md` endpoints, `frontend.md` page map; `PRODUCT.md` Lab surface; `docs/ROADMAP.md` step 3 status. Commit `feat(lab): runs list and compare`.

---

## Merge and ship

- [ ] Merge each wave's branches in task order; gate on main after each wave (in-image pytest + lint, node tests + build, `stale.py --orphans`).
- [ ] Final whole-branch review; one fix wave if needed.
- [ ] Deploy direct (`[skip ci]` on HEAD, push, `docker compose build backend ingest jobs && docker compose up -d backend` in `/home/ubuntu/deploys/NeoTrade`), outside 15:30-17:00 IST; next 16:00 pass writes the first `study` runs; check `lab_runs` count after it.
