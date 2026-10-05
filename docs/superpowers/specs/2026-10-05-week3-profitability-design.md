# Week 3: honest numbers, intraday parked, factor sized for real capital

Date: 2026-10-05 · Status: decisions made in chat (AskUserQuestion), awaiting spec review

From the 2026-10-05 audit (https://claude.ai/artifact/6haNohQe27A9Ss3JBVtNMQ), Profitability.

## Decisions (owner)

1. Intraday: turn the owner's daily intraday run **off**, default **off** for everyone, label it
   experimental. It can still be turned on.
2. Factor portfolio below ₹2 lakh: hold **top 8** instead of 15–20, skip stocks priced above a
   slot, model the DP charge.
3. Backtester: **full honest backtest** — the user's account settings, enforced stops/targets,
   next-bar fills, round-trip stats, DP charge, and a cost filter at sizing.

## Problem (measured)

- All four intraday strategies lose before charges (PF 0.63–0.80); stops/targets are never used
  as exits for intraday equity; fills are at the signal bar's own close.
- Backtests size a ₹10 lakh account with no per-trade cap: average fill ₹2.8–7.8 lakh, against a
  ₹25,000 account with a ₹5,000 cap. Win rate counts opening fills as trades.
- The DP charge (~₹15.93 per scrip per sell day on delivery) is not modelled anywhere.
- At ₹5,000 a trade, ~₹15 of friction against ~₹22 of risk: ~0.7R lost per trade.
- Factor book: 15–20 names × 10% cap on a small account breaks whole-share rounding.

## Design

### 1. Park intraday

- `backend/prefs.py`: `auto_paper_intraday` default `False`.
- Owner's pref set to `False` **after today's 15:30 close** (turning it off mid-session would stop
  the run before the 15:15 square-off).
- `EngineSettings.jsx` (Daily auto-run row): label "Paper-trade intraday every session —
  experimental: loses money after charges in every backtest so far".

### 2. Costs: the DP charge

- `backend/engine/execution/costs.py`: `DP_CHARGE = 15.93` (₹13.50 + 18% GST, CDSL via Zerodha),
  added to every **CNC SELL** fill. Applies to paper fills, backtests and sizing estimates alike.

### 3. Cost filter at sizing (`size_intents`)

- After sizing and trimming, an **entry** (not an exit) is skipped when its expected gain
  (`|target_hint − entry| × qty`) is below `COST_MULTIPLE = 3` × round-trip friction
  (buy + sell charges from `calculate_indian_costs` at that size, plus `2 × 10 bps` slippage).
  No `target_hint` → no filter (can't judge). Logged: `skipping intent for X: expected ₹a < 3 ×
  friction ₹b`.

### 4. Honest backtester (`backend/engine/backtest.py`)

- **Account settings**: `run_backtest(..., account_size, max_exposure, per_trade_cap)` all passed
  through to `run()`; `backtest_for_gate` and `learning/retune.py` read them from the triggering
  user's prefs (the gate is admin-triggered; the owner is the admin).
- **Next-bar fills**: a market order submitted on bar *t* fills at bar *t+1*'s **open** (plus
  slippage). `SimulatedExecutionClient(fill_on_next_open=True)` queues orders and fills them when
  the next bar for that symbol arrives; paper/live keep current behaviour.
- **Stops/targets for every equity position**, not only CNC buys: when a position is opened from
  an intent with `stop_hint`/`target_hint`, a later bar's **low/high** crossing the stop (or
  target) exits at that level (stop checked first — conservative). Intraday positions still square
  off at 15:15.
- **Round-trip stats**: `total_trades` and `win_rate` count closed round trips (a position going
  to flat), not fills; profit factor and net P&L unchanged in definition.

### 5. Factor portfolio on a small account (`backend/factor/`)

- `SMALL_ACCOUNT = 200_000`, `SMALL_TOP_N = 8`.
- `paper.rebalance` (and the factor backtest when given capital): `top_n = 8` when capital <
  ₹2 lakh; a chosen stock whose single share costs more than its slot (`capital × exposure ×
  weight`) is skipped and the next-ranked fills in.
- The DP charge (§2) applies to its sells.

## Testing

- costs: CNC sell includes DP; CNC buy and MIS do not.
- size_intents: entry skipped below 3× friction; exit never filtered; no target → not filtered.
- simulated: next-open fill uses the following bar's open; paper path unchanged.
- backtest: stop hit intrabar exits at the stop; target likewise; stop wins when both cross;
  round-trip counting (open+close = 1 trade); per-trade cap honoured (no fill above it).
- factor: top 8 below ₹2 lakh; over-priced name skipped and replaced.
- gate/retune pass the user's account settings.

## Out of scope

Intraday revival (real-time feed, liquid universe, walk-forward) — parked with the strategies.
Universe cleanup stays in this week but is a data fix: drop stale symbols (GMRINFRA, TATAMOTORS,
TATAMTRDVR, GUJGASLTD, GSPL) and anything under ₹50 from `ALL_SCAN_STOCKS`.
