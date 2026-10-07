# Strategy Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The AI drafts up to 3 intraday strategies a week as JSON block specs; each is backtested on a year of 5-minute history, and only passing ones join the library on paper.

**Architecture:** A closed block vocabulary is interpreted by one `BlockStrategy` class over incremental per-symbol indicator state (`backend/strategies/blocks/`). A weekly job (`python -m backend.builder`, spawned by Friday's 16:00 pass) asks the model for specs, validates them, backtests them through the existing `run_backtest`, and stores verdicts in `built_strategies`. Active specs sit in a process-level cache that `build_default_strategies` reads, so every existing caller (runs, gate, library, plan, retune) sees them with no signature change.

**Tech Stack:** Python 3 / FastAPI / Motor (Mongo) / pandas; React 19 + Vite frontend. Tests: `docker run --rm -v "$PWD":/app -w /app --entrypoint sh neotrade-backend -c "python -m pytest -q -p no:cacheprovider <path>"` from the repo root (no host Python). Frontend: `npx vitest run` and `npm run build` in `frontend/`.

**Spec:** `docs/superpowers/specs/2026-10-07-strategy-builder-design.md`

## Global Constraints

- `backend/strategies/` stays I/O-free and wall-clock-free (existing test `tests/test_strategies_io_free*` or equivalent must keep passing; no Mongo, Redis, network or `datetime.now` there).
- Built strategy names are `built:<slug>`; slug is lowercase `[a-z0-9-]`, ≤ 40 chars.
- Every built `Intent` has `reason_codes == ["built:<slug>", <setup>, *<filters in spec order>]` and a non-empty `stop_hint` and `target_hint`.
- `composite.py`, `AI_CAP`, `RULE_FLOOR`, kill switch, fence, backtest gate, paper gate: unchanged.
- Pass requires: `passes_gate(result)` AND last-90-day net P&L > 0 AND `deflated_sharpe(daily, trial_sharpes) >= 0.95` (`learning.retune.MIN_DSR`).
- At most 3 drafts per weekly run; at most 5 `active` built strategies.
- LLM call: `llm_service.get_completion(prompt, system_prompt=system, tier="deep", feature="learning")`; the prompt lives in `backend/prompts/strategy_builder.md`, rendered by `backend.prompts.render`.
- Commits: one per task, message ends with `[skip ci]` on the commit that is HEAD at push time (session deploy mode is Direct), plus the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.
- Handbook (`frontend/src/handbook/*.md`) and `PRODUCT.md` updated in the task that changes the behaviour they describe.

## Review Focus

1. A stored spec whose block or key no longer exists in the vocabulary (vocabulary changed later): loading it must skip it with a warning, never crash a run start. → Task 3 test `test_registry_skips_a_spec_that_no_longer_validates`.
2. A symbol with no prior session (first day in history, or a new listing): `gap` and `atr_pct` have no previous close / ATR yet; the block must stay silent, not divide by zero. → Task 2 test `test_gap_is_silent_without_a_previous_close`.
3. Two drafts in one run with the same blocks and numbers within one step: the second is rejected as a duplicate of the first, not only of stored specs. → Task 4 test `test_duplicate_within_the_same_batch_is_refused`.
4. The weekly job runs while a previous run is still backtesting (manual "Run now" during the Friday run): the second must exit at once on the Redis lock. → Task 6 test `test_second_run_exits_on_the_lock`.
5. A built strategy that opened a position must still close it by its time stop even if a later bar for that symbol fails a filter (filters gate entries only). → Task 3 test `test_time_stop_closes_even_when_filters_now_fail`.

---

### Task 1: Incremental indicator state

**Files:**
- Create: `backend/strategies/blocks/__init__.py` (empty), `backend/strategies/blocks/state.py`
- Test: `backend/tests/test_blocks_state.py`

**Interfaces:**
- Produces: `class SymbolState` with `update(bar: Bar, prev_close: float | None = None) -> None` and read-only attributes for the current session: `day` (date, IST), `bars_today: int`, `open`, `close`, `prev_close: float | None`, `vwap: float | None`, `atr: float | None` (14-period Wilder), `vol_avg20: float | None` (mean volume of the previous 20 bars, any session), `ema(period) -> float | None`, `rsi(period) -> float | None` (Wilder), `prev_rsi(period) -> float | None` (value one bar earlier), `range_high(minutes) / range_low(minutes) -> float | None` (opening range of today's first `minutes`, None until complete), `prev_bar: Bar | None`, `last_bar: Bar`, `prev_vwap: float | None`.
- `ema`/`rsi` periods must be registered up front: `SymbolState(ema_periods: set[int], rsi_periods: set[int], range_minutes: set[int])`.
- A new IST date resets VWAP, opening range, `bars_today`, and sets `prev_close` to the last close of the previous session (or the `prev_close` argument when given; it wins).

- [ ] **Step 1: Write the failing tests**

```python
def test_vwap_atr_ema_rsi_match_the_batch_indicators():
    # 120 synthetic 5m bars over 2 sessions (seeded random walk); feed them one by one.
    # For the last bar: abs(state.vwap - Indicators.vwap(...).iloc[-1]) < 1e-6 (session-reset VWAP),
    # abs(state.atr - Indicators.atr(...).iloc[-1]) < 1e-6, same for ema(9), ema(20), rsi(14).

def test_new_session_resets_vwap_and_range_and_sets_prev_close():
    # after the first bar of day 2: state.prev_close == last close of day 1,
    # state.bars_today == 1, state.range_high(15) is None until 3 bars of day 2 exist.

def test_explicit_prev_close_wins():
    # update(first_bar_of_day, prev_close=101.5) -> state.prev_close == 101.5
```

- [ ] **Step 2: Run** `... python -m pytest -q backend/tests/test_blocks_state.py` → FAIL (module missing).
- [ ] **Step 3: Implement `SymbolState`** in `state.py`. Wilder smoothing for ATR/RSI exactly as `components/quant/indicators.py` does (read it first; match its seeding so the parity test holds). O(1) per bar: no lists longer than 20 kept except the opening-range bars.
- [ ] **Step 4: Run** the tests → PASS. Also run the existing I/O-free test (`grep -rl "I/O-free\|io_free" backend/tests` to find it) → PASS.
- [ ] **Step 5: Commit** `feat(builder): incremental per-symbol indicator state`.

### Task 2: Block vocabulary and block functions

**Files:**
- Create: `backend/strategies/blocks/vocab.py`, `backend/strategies/blocks/blocks.py`
- Test: `backend/tests/test_blocks.py`

**Interfaces:**
- Consumes: `SymbolState` (Task 1).
- Produces:
  - `vocab.SETUPS`, `vocab.FILTERS`, `vocab.EXITS`: dicts `block -> {param: spec}` where a numeric spec is `(lo, hi, step)` and a choice spec is a tuple of allowed strings, exactly the ranges in the spec's §1 table. Steps: `range_minutes` 5, `min_pct` 0.25, `period` 1, `level` 5, `multiple` 0.25, `atr_multiple` 0.25, `r_multiple` 0.25, `minutes` 15, `min`/`max` 0.1. `time_window` takes `"HH:MM"` strings clamped to 09:20–14:45.
  - `blocks.setup_fires(name: str, params: dict, s: SymbolState, side: str) -> bool` — the six setups. `orb_break`: close crosses `range_high` (long) / `range_low` (short) this bar. `gap`: on any bar today, `(open_today/prev_close - 1)*100` is ≥ `min_pct` (up) or ≤ −`min_pct` (down) — true all day once gapped. `vwap_cross`: previous close on the other side of `prev_vwap`, this close on the `mode` side (`reclaim` = from below to above). `rsi_cross`: `prev_rsi` and `rsi` cross `level` in `direction`. `ema_pullback`: previous bar's low (long) / high (short) touched `ema(period)` and this bar closes beyond the previous bar's high (long) / low (short), with close on the trend side of the EMA. `volume_spike`: `last_bar.volume >= multiple * vol_avg20`.
  - `blocks.filter_passes(name: str, params: dict, s: SymbolState, regime: str | None, sector_rs: float | None, now_ist: time) -> bool` — six filters. A filter needing data it lacks (`regime` None, `sector_rs` None, `atr` None) returns False.
  - Any setup needing data it lacks returns False.

- [ ] **Step 1: Write failing tests**, one per block that fires and one that stays quiet, on crafted bars, plus:

```python
def test_gap_is_silent_without_a_previous_close():
    s = SymbolState(set(), set(), set()); s.update(first_bar_ever)
    assert setup_fires("gap", {"direction": "up", "min_pct": 1.0}, s, "long") is False

def test_filters_without_data_refuse():
    assert filter_passes("regime_is", {"regimes": ["risk_on"]}, s, None, None, time(10, 0)) is False
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(builder): block vocabulary and block functions`.

### Task 3: `BlockStrategy`, the active-spec cache, and the registry

**Files:**
- Create: `backend/strategies/built.py`, `backend/strategies/blocks/regime.py`
- Modify: `backend/strategies/registry.py` (append built strategies at the end of `build_default_strategies`)
- Test: `backend/tests/test_built_strategy.py`

**Interfaces:**
- Consumes: Tasks 1–2; `TokenResolvingStrategy`, `StrategySpec`, `StrategyCard`, `Intent`, `Side`; `builder.validate.validate_spec` is NOT imported here (strategies stay free of builder); instead `built.py` has its own `load_ok(spec) -> bool` that checks every block name and key exists in `vocab`.
- Produces:
  - `set_active(docs: list[dict]) -> None` and `active() -> list[dict]` — module-level cache of `{"slug", "spec", "params"}` docs. Pure data, no I/O.
  - `class BlockStrategy(TokenResolvingStrategy)`: `__init__(self, slug: str, spec: dict, universe, symbol_for_token, params: dict | None = None, regime_of: Callable[[date], str | None] | None = None, sector_of: dict[str, str] | None = None, thesis: str = "AI-built strategy.")`. `spec.name == f"built:{slug}"`, `mode="INTRADAY"`, `timeframe="5m"`, `warmup_bars=20`.
  - `PARAMS`: the spec's numeric params flattened as `"<kind>.<block>.<param>"` (e.g. `"setup.gap.min_pct"`); `GRID`: each numeric param at value − step, value, value + step, clamped. Instance attributes (set in `__init__`), not class attributes.
  - `CARD`: built per instance: style `breakout` for `orb_break`, `reversion` for `rsi_cross` or `vwap_cross` reclaim, else `momentum`; `regimes` from `regime_is` or all three; `needs` from setup (`gap`→`gap`, `volume_spike`→`volume_spike`, `orb_break`→`range_day`, else `trend_day`); `best_when` = `thesis` (constructor arg `thesis: str = "AI-built strategy."`); `avoid_when` = "Outside its time window or regimes."; `typical_hold_minutes` = `time_stop.minutes` or 120.
  - Regime: `regime_of(day) -> "risk_on" | "risk_off" | None` from `backend/strategies/blocks/regime.py::regime_by_day(nifty: list[tuple[date, float]]) -> Callable[[date], str | None]` (pure): the Nifty's previous close above its 200-day average → `risk_on`, below → `risk_off`, fewer than 200 closes → None. Live runs and backtests use the same function, so a `regime_is` spec trades the same way in both; `neutral` is never produced (document it in the prompt's vocabulary).
  - Sector move: `sector_of: dict[str, str]` constructor arg (the registry already receives `sector_of`). On each bar, a symbol's sector RS = mean session return (close / today's open − 1, in %) of its sector's symbols minus the mean over the whole universe, from each symbol's `SymbolState`; a sector with fewer than 3 symbols → None. Pass it to `filter_passes` as `sector_rs`.
  - Entry: when not holding the symbol (`ctx.position(symbol)` is None or quantity 0), the setup fires on this bar, and every filter passes → `ctx.submit(Intent(side=BUY for long / SELL for short, strength=0.6, reason_codes=[...], stop_hint, target_hint))`. Stop: `close ∓ atr_multiple*atr`, or the setup bar's low/high for `setup_bar`. Target: `close ± r_multiple*|close − stop|`. No ATR → no entry.
  - Exit: while holding a position this strategy opened (track entry time per symbol in `on_fill` or on submit), when `time_stop.minutes` have elapsed since entry → submit the closing Intent (`reason_codes=["built:<slug>", "time_stop"]`, stop/target None). Filters never gate exits. Stop/target exits stay with the engine, as for built-ins.
  - `registry.build_default_strategies` gains keyword `regime_of: Callable | None = None` and appends `BlockStrategy(d["slug"], d["spec"], universe, symbol_for_token, params.get(f"built:{d['slug']}") or d.get("params"), regime_of=regime_of, sector_of=sector_of, thesis=d.get("thesis") or "AI-built strategy.")` for each `d in active()` with `load_ok(d["spec"])`; a doc failing `load_ok` is skipped with `logger.warning`.

- [ ] **Step 1: Write failing tests**

```python
def test_gap_down_vwap_reclaim_fires_once_with_reason_codes():
    # the spec's §1 example, a crafted day: gap −1.5%, dips, reclaims VWAP on 2.2x volume at 10:05 IST
    # -> exactly one Intent, side BUY, reason_codes == ["built:gdvr", "gap", "price_vs_vwap", "volume_confirm", "time_window"]
    #    (filters in spec order), stop == close - 1.0*atr, target == close + 2*(close - stop)

def test_time_stop_closes_even_when_filters_now_fail():
    # spec with time_stop 30, filter time_window ends 10:10; entry at 10:05; at 10:35 position held
    # -> closing Intent with reason_codes ["built:x", "time_stop"]

def test_grid_is_one_step_either_side_and_clamped():
    # target.r_multiple 1.0 -> GRID["target.target.r_multiple"] == [1.0, 1.25]  (1.0 is the floor)

def test_registry_adds_active_specs_and_skips_a_spec_that_no_longer_validates(caplog):
    set_active([{"slug": "ok", "spec": EXAMPLE}, {"slug": "old", "spec": {"setup": {"gone": {}}, ...}}])
    names = [s.spec.name for s in build_default_strategies(universe=["X"])]
    assert "built:ok" in names and "built:old" not in names
    set_active([])

def test_regime_by_day_and_sector_rs():
    # 201 Nifty closes rising -> regime_of(next day) == "risk_on"; 199 closes -> None
    # 3 BANK symbols up 2% and 3 IT symbols flat -> a BANK symbol's sector RS == 1.0

def test_throughput_at_least_1000_bars_per_second():
    # 50_000 synthetic bars over 10 symbols through on_bar with a minimal ctx stub; elapsed < 50 s
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new tests and the existing registry/library/strategy tests (`backend/tests/test_strategies*.py`, `test_library*.py`) → PASS (a test asserting every registered strategy has a `CARD` must still pass).
- [ ] **Step 5: Commit** `feat(builder): BlockStrategy interprets block specs; registry loads active ones`.

### Task 4: Spec validator and plain-words description

**Files:**
- Create: `backend/builder/__init__.py` (empty), `backend/builder/validate.py`
- Test: `backend/tests/test_builder_validate.py`

**Interfaces:**
- Consumes: `vocab` (Task 2).
- Produces:
  - `validate_spec(raw: dict, existing: list[dict]) -> tuple[dict | None, str]` → `(clean_spec, "")` or `(None, reason)`. Drops unknown blocks/keys, clamps numbers to range and snaps to step, keeps at most 3 distinct filters (first three), requires exactly one setup, `side` in long/short, `stop` and `target`. Duplicate: same setup name, same filter names, same side, and every numeric param within one step of an `existing` spec → `(None, "duplicate of <slug>")`.
  - `slugify(spec: dict) -> str`: deterministic, e.g. `"gap-down-vwap-above-long"`, from setup, main param choice, first filter and side; ≤ 40 chars; caller appends `-2`, `-3` on collision.
  - `describe(spec: dict) -> str`: one sentence, e.g. the spec's example sentence for the spec's example.

- [ ] **Step 1: Write failing tests**

```python
def test_clamps_and_snaps(): ... {"gap": {"min_pct": 9}} -> 4.0 ; {"min_pct": 1.1} -> 1.0
def test_unknown_block_dropped_and_no_stop_refused(): -> (None, "no stop")
def test_two_setups_refused(): -> (None, "exactly one setup")
def test_duplicate_within_the_same_batch_is_refused():
    a, _ = validate_spec(EXAMPLE, []); b, why = validate_spec(EXAMPLE_PLUS_ONE_STEP, [{"slug": "a", "spec": a}])
    assert b is None and why == "duplicate of a"
def test_describe_reads_the_example():
    assert describe(EXAMPLE) == "Long when the stock gapped down at least 1% and is above VWAP on 2× volume, 9:30 AM–2:45 PM; stop 1× ATR, target 2R."
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(builder): spec validator and plain-words description`.

### Task 5: Store, cache refresh at every entry point

**Files:**
- Create: `backend/builder/store.py`
- Modify: `backend/server.py` (startup), `backend/plan/replay.py`, `backend/routers/trading.py::launch_run` (before `build_default_strategies`), `backend/risk/gate_backtest.py::backtest_for_gate`, `backend/learning/retune.py::_main`, `backend/learning/library.py::catalog`, `backend/scheduler.py` (start of the daily pass, before plan replays)
- Test: `backend/tests/test_builder_store.py`

**Interfaces:**
- Consumes: `built.set_active` (Task 3).
- Produces:
  - `COLLECTION = "built_strategies"`; doc fields: `slug, spec, thesis, description, drafted_at, status ("testing"|"rejected"|"active"|"retired"), verdict, metrics ({"year": {...}, "holdout": {...}}), trials, sharpe, params`.
  - `async def refresh(db) -> list[dict]`: reads `status == "active"`, calls `set_active`, returns the docs.
  - `async def all_drafts(db) -> list[dict]` (newest first, no `_id`), `async def insert(db, doc) -> None`, `async def set_status(db, slug, status, verdict="", **fields) -> None`, `async def trial_sharpes(db) -> list[float]` (`sharpe` of every tested draft, any status except `testing`).
- Every modified entry point calls `await store.refresh(db)` once before building strategies (in `catalog`, before `_strategies()`).
- `launch_run`, `backtest_for_gate`, `plan/replay.py` and the builder's backtest pass `regime_of=regime_by_day(await _nifty())` (`backend/portfolio/service.py::_nifty`, converted to `(date, close)` pairs) to `build_default_strategies`.

- [ ] **Step 1: Write failing tests** (mongomock): `refresh` loads only `active`; `trial_sharpes` excludes `testing`; `launch_run` path: after inserting an active doc, `catalog(...)` lists `built:<slug>` (call `catalog` with the mock db and an empty nifty list).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; then the full suite → PASS.
- [ ] **Step 5: Commit** `feat(builder): built_strategies store, active specs loaded at every run start`.

### Task 6: The weekly drafting job

**Files:**
- Create: `backend/builder/draft.py`, `backend/builder/__main__.py`, `backend/prompts/strategy_builder.md`
- Modify: `backend/risk/gate_backtest.py` (extract `async def gate_universe(db) -> tuple[list[Instrument], dict[int, str]]` from `backtest_for_gate`, used by both), `backend/scheduler.py` (Friday: `await draft.start_if_due(db, now)` beside the re-tune start), `backend/system/jobs.py` (`BUILDER = "strategy_builder"`)
- Test: `backend/tests/test_builder_draft.py`

**Interfaces:**
- Consumes: Tasks 3–5; `run_backtest`, `backtest_account`, `intraday_history`, `BacktestGateStore.record`, `passes_gate`, `retune._daily`, `retune._sharpe`, `retune.MIN_DSR`, `deflated_sharpe`, `learning.adapt` state (`learning_state` doc of the admin: `paused` dict name → since), `notify` (admin), `jobs.mark`.
- Produces:
  - `async def start_if_due(db, now) -> bool`: Fridays (IST) only, once per ISO week via `builder_runs` `{"week": "2026-W41"}`; spawns `nice -n 15 python -m backend.builder` exactly like `retune.spawn`.
  - `async def run(db, redis, now, llm=None, backtest=None) -> dict`: the whole job; `llm(system, prompt) -> str` and `backtest(strategy, start, end) -> BacktestResult` are injectable (defaults: `llm_service.get_completion(..., tier="deep", feature="learning")` and `run_backtest` over `gate_universe` with `backtest_account` sizing, start `now − 365 days`). Returns `{"drafted": n, "passed": [slugs], "rejected": [(slug, reason)], "retired": [slugs]}`.
  - Order inside `run`: Redis lock `builder:lock` (SET NX, 6 h TTL; held → return `{"skipped": "running"}`); retire actives paused ≥ 30 days in the admin's `learning_state`; retry drafts still `testing`; render the prompt with `plans` (last 5 trading days of `trade_plans` for all users: `allow`, `rationale`, `skip_day`), `scorecards` (last 4 weeks of `plan_scorecards`), `library` (catalog for the admin, INTRADAY), `setups` (worst 10 attribution rows, as hypotheses does), `drafts` (every stored draft: description, verdict, metrics); parse `{"strategies": [{"spec": {...}, "thesis": "..."}]}`; validate each against stored drafts plus earlier ones in this batch; insert valid ones as `testing`, invalid as `rejected`; backtest each (no history source → leave `testing`, stop); pass test per Global Constraints (holdout = trades with timestamp ≥ end − 90 days, sum `net_pnl` > 0; DSR over `_daily(trades, start, end)` with `trial_sharpes(db)` + this draft's sharpe); record the gate row as `built:<slug>`; pass → `active` (if 5 active already, retire the active one with the lowest paper net across users, ties oldest `drafted_at`); fail → `rejected` with the first failing reason (`"gate: PF 1.12 < 1.3"`, `"holdout: −₹840 over the last 90 days"`, `"deflated Sharpe 0.71 < 0.95 over 7 drafts"`); `jobs.mark(redis, BUILDER, ok=True, note=...)`; one admin notify line: `"🧪 Strategy builder: 3 drafted, 1 passed: built:<slug> (PF 1.41, 312 trades, last 90 days +₹2,140)."`
  - `__main__.py`: connect db, `await run(db.db, db.redis, datetime.now(timezone.utc))`, print the result.
  - Prompt `strategy_builder.md`: front matter system prompt saying the model writes block specs only from the vocabulary table (embedded), ≤ 3, each needs a different idea and a one-line `thesis`; placeholders `{{vocabulary}}`, `{{plans}}`, `{{scorecards}}`, `{{library}}`, `{{setups}}`, `{{drafts}}`; output JSON schema above. `{{vocabulary}}` is rendered from `vocab` so it never drifts.

- [ ] **Step 1: Write failing tests** with stubbed `llm` and `backtest`:

```python
async def test_pass_becomes_active_and_records_the_gate_row(): ...  # PF 1.5, 300 trades, DD .08, 365 d, holdout +, DSR high
async def test_gate_fail_is_rejected_with_reason(): ...           # verdict startswith "gate:"
async def test_holdout_fail_is_rejected(): ...                     # all profit before the last 90 days
async def test_deflated_sharpe_fail_is_rejected(): ...             # many prior trial sharpes stored
async def test_invalid_and_duplicate_drafts_are_rejected_not_tested(): ...  # backtest stub never called for them
async def test_sixth_pass_retires_the_weakest_active(): ...
async def test_paused_30_days_is_retired(): ...
async def test_no_history_source_leaves_drafts_testing(): ...
async def test_second_run_exits_on_the_lock(): ...                 # lock pre-set -> {"skipped": "running"}, llm not called
async def test_start_if_due_only_fridays_once_a_week(): ...
async def test_llm_garbage_drafts_nothing(): ...                   # returns drafted 0, job marked ok
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `feat(builder): weekly drafting job, Friday night, gate + holdout + deflated Sharpe`.

### Task 7: API, chat fact, jobs panel

**Files:**
- Modify: `backend/routers/settings.py` (`GET /strategies/built`), `backend/system/router.py` (`POST /system/builder/run`, admin), `backend/system/status.py` (`_jobs` lists `BUILDER` last run), `backend/learning/library.py::catalog` (rows for `built:*` add `built: {"description", "thesis", "metrics"}`), `backend/ai/facts/user.py` (fact `built_strategies`, not user-scoped), `backend/chat/tools.py` (tool `get_built_strategies` wrapping the fact)
- Test: `backend/tests/test_builder_api.py`

**Interfaces:**
- Consumes: `store.all_drafts`, `draft.run`.
- Produces: `GET /strategies/built` → `{"active": [...], "rejected": [...], "retired": [...], "testing": [...]}` (each: slug, description, thesis, verdict, metrics, drafted_at); `POST /system/builder/run` → `{"started": true}` (spawns the process like `start_if_due` without the weekday check) or 409 `"The builder is already running."` when `builder:lock` is set.

- [ ] **Step 1: Failing tests:** endpoint groups by status; non-admin gets 403 on run; run while locked → 409; chat tool returns the active list; catalog row for a built strategy carries `built.description`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(builder): built strategies over the API, chat and the Jobs panel`.

### Task 8: Frontend and docs

**Files:**
- Modify: `frontend/src/pages/Strategies.jsx` (Built badge, description, thesis, year/holdout line on built rows; a folded "Tried and rejected" list from `GET /strategies/built`), `frontend/src/utils/api.js` (`endpoints.builtStrategies`, `endpoints.system.builderRun`), the handbook Jobs panel component (find with `grep -rn "jobs" frontend/src/pages/Handbook.jsx frontend/src/components/handbook`) gets a "Run now" button for the builder, `frontend/src/handbook/trading-and-money.md` (Strategy builder section), `frontend/src/handbook/jobs-and-ops.md` (Friday builder job), `PRODUCT.md` (Practice → Strategies row), `docs/ROADMAP.md` (Phase 17.3 note: builder landed)
- Test: existing vitest suite; add `frontend/src/utils/library.test.js` case if `statusOf` needs a `built` branch.

- [ ] **Step 1:** Implement the UI; copy for the badge is `Built`, the fold heading `Tried and rejected`, the row line `{description} — {thesis}`, the result line `Year: PF {pf}, {trades} trades · Last 90 days {net}`.
- [ ] **Step 2: Run** `npx vitest run` and `npm run build` in `frontend/` → both pass.
- [ ] **Step 3: Commit** `feat(builder): built strategies on Practice › Strategies; Run now on the Jobs panel; docs [skip ci]`.

### Task 9: Deploy and smoke

- [ ] **Step 1:** Full backend suite in the image → all pass.
- [ ] **Step 2:** Push; in `/home/ubuntu/deploys/NeoTrade`: `git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend ingest`; `curl -s localhost:8000/health` → 200.
- [ ] **Step 3:** Outside market hours, `POST /system/builder/run` as admin (or `docker exec neotrade-backend python -m backend.builder`); expect a printed result dict and, with an Upstox session, drafts moving from `testing` to `active`/`rejected` within ~25 min each. Report what it drafted.
