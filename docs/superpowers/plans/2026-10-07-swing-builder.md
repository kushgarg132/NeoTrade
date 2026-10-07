# Swing Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block strategies gain a swing horizon (daily bars, long only, multi-day holds) that the AI builder, the form and the chat can compose; passing ones file long-term proposals and exit by stop, target, trailing stop or max hold.

**Architecture:** A spec's `horizon` ("intraday" default, "swing") routes the validator, interpreter, checks and store; swing blocks read incremental daily state; `BlockStrategy` in swing mode is a LONGTERM / 1d strategy so the 4 PM scan files its proposals; `Intent.max_hold_days` and `trail_atr` ride onto proposals and are enforced by every long-term exit path and by the backtester.

**Tech Stack:** Python / FastAPI / Motor; React 19 + Vite. Tests from the repo root: `docker run --rm -v "$PWD":/app -w /app --entrypoint sh neotrade-backend -c "python -m pytest -q -p no:cacheprovider <path>"`; frontend `cd frontend && npm run build`.

**Spec:** `docs/superpowers/specs/2026-10-07-swing-builder-design.md`

## Global Constraints

- A spec without `horizon` is intraday and behaves exactly as today (every existing builder/user-strategy test keeps passing unchanged).
- Swing is long only; every swing spec has `stop`, `target` and `max_hold_days`. Vocabulary ranges/steps exactly as the spec's §1 table.
- Swing checks: `passes_gate` AND last 180 days net > 0 AND Deflated Sharpe ≥ 0.95 over that owner's **swing** trials AND net return over the window > equal-weight buy-and-hold of the same universe net of one round trip. Failure verdict for the last: `benchmark: +x% < buy-and-hold +y%` (one decimal, explicit sign).
- Swing window: 3 years of trading plus 300 days warm-up, from `daily_bars` via `StoreHistoryProvider`; delivery (CNC) charges and 10 bps slippage per side.
- Caps: 5 active per owner **per horizon** (AI `_make_room` too); 3 submissions/day and one testing at a time stay shared per user.
- `backend/strategies/` stays I/O-free; sizing stays in `size_intents`; scoping by owner unchanged.
- Commits: subject ends ` [skip ci]`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. `StoreHistoryProvider` has no period beyond "2y", so a 4-year swing request silently falls back to yfinance → must read Mongo. → Task 5 `test_store_provider_serves_five_years`.
2. A paper position opened from a swing proposal must exit at `max_hold_days` even if the price never hits stop or target, in `check_exits` AND the autopilot's own exit check. → Task 4 `test_max_hold_exit_paper_and_autopilot`.
3. Trading-day counting for max hold skips weekends (a Friday entry with 3 days exits Wednesday, not Monday). → Task 4 `test_max_hold_counts_trading_days`.
4. Intraday trials and swing trials never mix in the Deflated Sharpe count. → Task 5 `test_trials_are_per_horizon`.
5. A swing spec submitted with `side: "short"` is cleaned to long, never refused silently differently between form and chat. → Task 2 `test_swing_side_is_always_long`.

---

### Task 1: Swing state, blocks and vocabulary

**Files:** Create `backend/strategies/blocks/swing_state.py`, `backend/strategies/blocks/swing.py`; modify `backend/strategies/blocks/vocab.py`. Test: `backend/tests/test_swing_blocks.py`.

**Interfaces — produces:**
- `vocab.SWING_SETUPS`, `vocab.SWING_FILTERS`, `vocab.SWING_EXITS` in the existing spec forms (numeric `(lo, hi, step)`, choice tuple, flag `()`); choices for `trend` `("50","100","200")`, `pull` `("10","20")`, `lookback` `("63","126")`, `period` `("50","100","200")` as strings; `swing_low` a flag one-of with `atr_multiple`.
- `SwingState()` with `update(bar)` (daily `Bar`) and attributes: `close, open, high, low, prev_close, prev_high, prev_low, volume, sma(n) for n in 10/20/50/100/200, atr (14, same formula as Indicators.atr), rsi2, vol_avg20, turnover_avg20 (close×volume, ₹), high_n(n) / low_n(n)` (prior n bars, excluding today), `ret(n)` (close / close n bars ago − 1), `bars`.
- `swing.setup_fires(name, params, s: SwingState, rank_pct: float | None) -> bool` and `swing.filter_passes(name, params, s, regime, sector_rs) -> bool`, semantics exactly as the spec §1 table; missing data → False. `momentum_rank` reads `rank_pct` (0 = best, 100 = worst) supplied by the caller.

- [ ] Step 1: failing tests — each setup fires/quiet on crafted daily series; `test_swing_state_matches_batch_indicators` (SMA 50, ATR 14, RSI 2 vs `components/quant/indicators.py` on 300 bars); `test_missing_history_is_silent` (`breakout_n` with < n bars → False).
- [ ] Step 2–4: RED, implement, GREEN; `test_no_network_in_strategies.py` passes.
- [ ] Step 5: commit `feat(builder): swing state, blocks and vocabulary`.

### Task 2: Validator and description by horizon

**Files:** Modify `backend/builder/validate.py`. Test: `backend/tests/test_builder_validate.py` (append).

**Interfaces — produces:** `validate_spec(raw, existing)` reads `raw.get("horizon")` (anything but "swing" → "intraday"; key written into the clean spec only when swing) and cleans against that horizon's vocab; swing: `side` forced "long", `max_hold_days` required ("no max hold"), `trail_atr` optional; duplicates compare only specs of the same horizon. `describe(spec)` for swing reads like "Swing, long: close above the 20-day high with volume ≥ 2×, above the 200-day average; stop 2× ATR, target 3R, trailing 3× ATR, out after 15 days." `slugify` prefixes swing slugs with `swing-`.

- [ ] Step 1: failing tests `test_swing_spec_validates_and_describes`, `test_swing_side_is_always_long`, `test_swing_needs_max_hold`, `test_intraday_spec_unchanged_without_horizon`, `test_duplicate_only_within_horizon`, hostile-input parametrized test extended to swing specs.
- [ ] Step 2–4: RED, implement, GREEN. Step 5: commit `feat(builder): validator routes specs by horizon`.

### Task 3: BlockStrategy swing mode, Intent fields, proposals

**Files:** Modify `backend/strategies/built.py`, `backend/core/models.py` (`Intent`), `backend/suggestions/store.py` (`create` copies the two fields), `backend/engine/runner.py` only if `entry_context`/order context must carry them, `backend/strategies/registry.py` (swing built strategies are `mode="LONGTERM"`). Test: `backend/tests/test_built_strategy.py` (append), `backend/tests/test_suggestion_scan.py` (append).

**Interfaces — produces:**
- `Intent.max_hold_days: Optional[int] = None`, `Intent.trail_atr: Optional[float] = None` (ATR multiple; the absolute trail is computed by exit code from the bars).
- Suggestion docs gain `max_hold_days`, `trail_atr`; paper trades opened from them keep `suggestion_id` (exits read the suggestion, as today).
- `BlockStrategy` swing: `spec.mode == "LONGTERM"`, `timeframe "1d"`, `warmup_bars 200`; one entry per symbol per 5 trading days (counted in bars seen); stop = close − k×ATR or the 5-bar low (`swing_low`); target = close + R×(close − stop); intents carry `max_hold_days` and `trail_atr`; `momentum_rank` and `sector_rs` from the day's cross-section of `SwingState`s (rank over symbols that have `ret(lookback)`), sectors via `sector_of`.
- `suggestions/scan.py` already builds LONGTERM strategies with the user's id — confirm built swing strategies are included and file proposals.

- [ ] Step 1: failing tests `test_swing_breakout_fires_with_hold_fields`, `test_swing_enters_once_per_five_days`, `test_momentum_rank_uses_cross_section`, `test_scan_files_swing_proposal_for_owner_only`.
- [ ] Step 2–4: RED, implement, GREEN; full suite. Step 5: commit `feat(strategies): swing BlockStrategy files long-term proposals`.

### Task 4: Exits — max hold and trailing stop everywhere

**Files:** Modify `backend/suggestions/exits.py`, `backend/autopilot/service.py` (`check_exits`), `backend/engine/backtest.py` (level exits). Test: `backend/tests/test_suggestion_exits.py` (or the existing exits test file — grep), `backend/tests/test_engine_backtest*.py`.

**Interfaces — produces:**
- `exits.held_too_long(entry_at: datetime, now: datetime, max_hold_days: int) -> bool`: true once the number of NSE weekdays strictly after the entry's IST date up to and including today ≥ `max_hold_days` (weekends skipped; holidays ignored).
- `exits.trail_level(highest_close: float, atr: float, k: float) -> float = highest_close − k × atr`; the effective stop is `max(stop, trail_level)`, never lowered. Highest close since entry and ATR come from `daily_bars` (latest 14-day ATR); recorded on the trade as `trail_stop` when it rises.
- Exit reasons: `"max hold"`, `"trailing stop"` beside `"stop"`/`"target"`.
- Backtest: positions with `max_hold_days` exit at the close of the bar where the count is reached; trailing stop from closes since entry.

- [ ] Step 1: failing tests `test_max_hold_counts_trading_days`, `test_max_hold_exit_paper_and_autopilot`, `test_trailing_stop_only_rises`, `test_backtest_applies_max_hold_and_trail`.
- [ ] Step 2–4: RED, implement, GREEN; full suite. Step 5: commit `feat(exits): max hold and trailing stop for swing positions`.

### Task 5: Builder — swing tests, checks, weekly drafts, caps

**Files:** Modify `backend/data/providers/store.py` (`_PERIOD_DAYS` gains `"5y": 1826`), `backend/builder/draft.py`, `backend/builder/store.py`, `backend/prompts/strategy_builder.md` (or a second prompt `strategy_builder_swing.md`). Test: `backend/tests/test_builder_draft.py`, `backend/tests/test_builder_store.py` (append).

**Interfaces — produces:**
- `store.trial_sharpes(db, owner_id=None, exclude=None, horizon="intraday")` filters by horizon (absent = intraday).
- `draft._history(db, redis, horizon)`: intraday unchanged; swing → `StoreHistoryProvider(db)` over `gate_universe`, timeframe `"1d"`, window `now − (3×365 + 300) days` → `now`, metrics/holdout/benchmark computed only over the last 3 years (after warm-up). Fewer than 30 symbols with bars → None ("waiting for market history").
- `draft._benchmark(bars_by_symbol, start, end, charges_pct) -> float`: equal-weight buy-and-hold net return over [start, end] of symbols with bars at both ends, minus one round trip of delivery charges (use `execution/costs.py` for a ₹ per_trade_cap ticket, as a %).
- `_test` swing checks in this order: gate → holdout (180 days) → DSR (swing trials) → benchmark; verdict strings per Global Constraints; metrics add `"benchmark": {"strategy_pct", "buy_hold_pct"}`.
- Weekly `_run`: one LLM call per horizon (≤ 3 drafts each), each with its own vocabulary (`_vocabulary(horizon)`) and its horizon's past drafts; `_make_room(db, horizon)` caps 5 AI actives per horizon.
- `test_one` dispatches on the doc's horizon.

- [ ] Step 1: failing tests `test_store_provider_serves_five_years`, `test_swing_draft_passes_all_four_checks`, `test_swing_rejected_on_benchmark_with_verdict`, `test_swing_holdout_is_180_days`, `test_trials_are_per_horizon`, `test_weekly_run_drafts_both_horizons`, `test_make_room_per_horizon`, `test_swing_waits_with_too_few_symbols`.
- [ ] Step 2–4: RED, implement, GREEN; full suite. Step 5: commit `feat(builder): swing drafts tested on stored daily bars against buy-and-hold`.

### Task 6: API, chat, form, docs

**Files:** Modify `backend/routers/settings.py` (vocabulary by horizon; active cap per horizon), `backend/chat/actions.py` (`propose_strategy` description lists both vocabularies; spec carries `horizon`), `frontend/src/components/strategies/NewStrategySheet.jsx` (`Horizon` choice `Intraday` / `Swing`, swing has no Short and requires `Max hold (days)`), `frontend/src/pages/Strategies.jsx` + `MyStrategies.jsx` (horizon chip `Intraday` / `Swing`), `frontend/src/handbook/trading-and-money.md`, `PRODUCT.md`, `docs/ROADMAP.md` (Phase 18.1 landed note). Test: `backend/tests/test_user_strategies_api.py`, `backend/tests/test_chat_actions.py` (append); `npm run build`.

**Interfaces — produces:** `GET /strategies/vocabulary` → `{"intraday": {setups, filters, exits}, "swing": {setups, filters, exits}}`; list items add `horizon`; active-cap 409 counts actives of the submitted spec's horizon.

- [ ] Step 1: failing tests `test_vocabulary_has_both_horizons`, `test_active_cap_is_per_horizon`, `test_chat_swing_strategy_card`.
- [ ] Step 2–4: RED, implement, GREEN; `npm run build`. Step 5: commit `feat(strategies): swing horizon in the form, chat and API`.

### Task 7: Deploy and smoke

- [ ] Full suite passes; push; deploy backend + ingest; `/health` 200.
- [ ] As the admin: submit a swing spec (breakout_n 20, trend_ma 200, stop 2×ATR, target 3R, max hold 15) via the API; it settles within ~2 minutes; report verdict and metrics including the benchmark.
