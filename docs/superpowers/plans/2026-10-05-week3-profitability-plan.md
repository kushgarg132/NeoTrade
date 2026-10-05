# Week 3 Profitability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Honest backtests, intraday parked, factor book sized for small capital, DP charge and a cost filter.
**Spec:** `docs/superpowers/specs/2026-10-05-week3-profitability-design.md`
**Tech:** Python/FastAPI, pandas, pytest; React for one label.

## Global Constraints
- `DP_CHARGE = 15.93` on CNC SELL fills only. `COST_MULTIPLE = 3`. Slippage for the filter `2 × 10 bps` of notional.
- `SMALL_ACCOUNT = 200_000`, `SMALL_TOP_N = 8`.
- Backtest-only behaviour (next-open fills, intrabar stops) never changes paper/live fills.
- Exits are never filtered or trimmed by the cost filter.
- Every task: failing test first; `python3 -m pytest -q -p no:cacheprovider` green before commit.

## Review Focus
1. A position opened with no `stop_hint`/`target_hint` in a backtest → no level exit, no crash.
2. The last bar of a backtest with a queued next-open order → order never fills (no phantom fill at end).
3. Cost filter with an intent whose target is on the wrong side of entry → treated as no expected gain (skipped), not negative-abs.
4. Factor small account where every chosen name is over-priced → book stays cash, no crash.
5. Gate backtest for a user with no prefs → falls back to defaults.

### Task 1: DP charge (`engine/execution/costs.py`, test `test_costs_dp.py`)
CNC sell = old charges + 15.93; CNC buy / MIS sell unchanged. Update any existing cost assertions that change.

### Task 2: Cost filter (`engine/runner.py` size_intents, test in `test_size_intents.py`)
Entry with target gain < 3 × (buy+sell charges + 0.2% notional) skipped; exit not filtered; no target not filtered; wrong-side target skipped.

### Task 3: Next-open fills (`engine/execution/simulated.py` `fill_on_next_open`, test `test_simulated_next_open.py`)
Queued orders fill on the symbol's next `on_bar` at that bar's open (+slippage); default False keeps paper behaviour; an order with no next bar never fills.

### Task 4: Honest backtest (`engine/backtest.py`, `risk/gate_backtest.py`, `learning/retune.py`; tests `test_backtest_honest.py`)
`per_trade_cap` passed to `run()`; next-open execution; intrabar stop/target exits for every equity position opened with levels (stop first); round-trip `total_trades`/`win_rate`; gate and retune read account settings from the user's prefs (owner) with defaults.

### Task 5: Factor small account (`factor/model.py`, `factor/paper.py`; test `test_factor_small.py`)
`top_n = 8` below ₹2 lakh; over-priced names skipped and replaced by next-ranked; all over-priced → cash.

### Task 6: Park intraday + universe cleanup
`prefs.py` default `auto_paper_intraday=False`; EngineSettings label; drop stale symbols and sub-₹50 names from `ALL_SCAN_STOCKS` (verify prices with one batched download); tests updated where they assumed the default.

### Task 7: Deploy; after 15:30 IST set the owner's `auto_paper_intraday` to False; verify.
