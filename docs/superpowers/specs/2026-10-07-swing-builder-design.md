# Swing builder (Phase 18.1): block strategies on daily bars, multi-day holds

User-approved design, 2026-10-07. Extends the strategy builder
(`2026-10-07-strategy-builder-design.md`) and user strategies
(`2026-10-07-user-strategies-design.md`) to a second horizon.

## Intent

Every intraday rule tested so far loses after charges (PF 0.88–0.96 over 200–1,600 trades): at
₹5,000 tickets the ~0.11% round trip is larger than the move a 5-minute rule captures. A swing
trade held 3–40 days targets a 3–8% move, so delivery charges (~0.25% round trip) are a small
share of it. This phase lets the AI builder, the New strategy form and the chat compose
**swing** strategies from daily-bar blocks, test them on 3 years of stored daily bars, and,
if they pass, file proposals that the user approves or the autopilot takes.

Success: swing drafts and user swing strategies test in seconds from stored bars; a passing
one files proposals after the 4 PM scan and exits by stop, target or a maximum hold; no
strategy passes unless it also beats buy-and-hold of the same stocks over the same window.

### Decisions (from the brainstorm)

| Question | Decision |
|---|---|
| Shape | Extend the builder: a spec gains `"horizon": "intraday" \| "swing"`; one validator, store, interpreter, checks, form and chat. |
| Execution | **Proposals** after the 4 PM scan (approve in Decisions, or the autopilot takes them); exits by the existing long-term exit checker plus a max hold. |
| Data | `daily_bars` in Mongo (2016 → today, 228 symbols) through `data/providers/store.py::StoreHistoryProvider`. |
| Extra check | Beat equal-weight buy-and-hold of the same universe over the same window (cancels most survivorship flattery). |

### Invariants

1. A spec without `horizon` is intraday and behaves exactly as today.
2. Swing is long only (no short delivery). Every swing spec has a stop, a target and
   `max_hold_days`, so every position exits.
3. Sizing stays in `size_intents`; conviction stays in `composite.py`; kill switch, fence,
   backtest gate and paper gate unchanged; user strategies stay private to their owner.
4. `backend/strategies/` stays I/O-free and wall-clock-free.

## 1. Swing vocabulary (`backend/strategies/blocks/vocab.py`, `SWING_SETUPS` / `SWING_FILTERS` / `SWING_EXITS`)

| Kind | Block | Parameters (range, step) |
|---|---|---|
| Setup (1) | `breakout_n` | `days` 10–60, 5 — close above the prior N-day high |
| | `pullback_ma` | `trend` 50/100/200 (choice), `pull` 10/20 (choice) — close above the trend average, the prior bar's low at or below the pull average, this close above the prior high |
| | `rsi2_dip` | `level` 2–15, 1 — 2-day RSI below level while close is above the 200-day average |
| | `gap_hold` | `min_pct` 1.0–6.0, 0.5 — open ≥ prior close × (1 + min_pct) and close ≥ open |
| | `momentum_rank` | `lookback` 63/126 (choice), `top_pct` 5–30, 5 — return rank within the universe on that day |
| | `volume_breakout` | `multiple` 1.5–5.0, 0.25 — volume ≥ k × 20-day average and close in the top 25% of the day's range |
| Filters (0–3) | `trend_ma` | `period` 50/100/200 (choice) — close above it |
| | `regime_is` | as intraday |
| | `sector_rs` | `min` −5.0–5.0, 0.5 — sector's 20-day return minus the universe's, in % |
| | `atr_pct` | `min` 0.5–4.0, `max` 1.0–8.0, 0.1 — 14-day ATR / close × 100 |
| | `liquidity` | `min_cr` 1–50, 1 — 20-day average turnover in ₹ crore |
| Exits | `stop` | `atr_multiple` 1.0–4.0, 0.25, or `swing_low` (lowest low of the last 5 bars) |
| | `target` | `r_multiple` 1.0–6.0, 0.25 |
| | `max_hold_days` | `days` 3–40, 1 (required) |
| | `trail_atr` | `multiple` 1.5–5.0, 0.25 (optional) — the stop rises to close − k × ATR, never falls |

`side` is always long for swing; the validator drops any other value.

## 2. Interpreter and execution

- `backend/strategies/blocks/swing_state.py`: incremental per-symbol daily state (SMA 10/20/50/
  100/200, ATR 14, RSI 2, 20-day volume and turnover averages, rolling N-day highs/lows, 63/126-
  day returns). `momentum_rank` and `sector_rs` read the day's cross-section of states, as
  intraday `sector_rs` does.
- `BlockStrategy` takes the horizon from the spec: swing -> `mode="LONGTERM"`, `timeframe="1d"`,
  `warmup_bars=200`; once per symbol per 5 trading days (a fresh signal after a stop-out must
  wait). Intents carry `stop_hint`, `target_hint` and `max_hold_days` (new optional `Intent`
  field, copied onto the proposal and the paper trade).
- Execution is the long-term path: the 4 PM scan (`suggestions/scan.py`) builds strategies with
  the scanning user's `user_id`, so active swing built strategies (global and that user's own)
  file proposals; the user approves in Decisions or the autopilot takes them.
- Exits: `suggestions/exits.py::check_exits` (every 15 min in session) gains "held
  `max_hold_days` trading days" and the trailing stop beside stop and target. The engine's
  backtest applies the same rules (`engine/backtest.py` level exits gain max hold and trail).

## 3. Test and checks (`backend/builder/draft.py`)

- History: `StoreHistoryProvider` over the default scan universe (`gate_universe`), window
  `now − 3 years − 300 days warm-up` to `now`; delivery charges (`execution/costs.py`, product
  CNC) and 10 bps slippage per side; sized with the owner's prefs.
- Pass needs all of:
  - the gate (`passes_gate`: ≥ 30 trades, PF ≥ 1.3, max DD ≤ 15%, span ≥ 365 days);
  - the last 180 days net-positive (holdout);
  - Deflated Sharpe ≥ 0.95, counting that owner's trials **for the swing horizon only**;
  - **benchmark**: the strategy's net return over the window beats an equal-weight
    buy-and-hold of the same universe over the same window (computed from the same bars, net
    of one round trip of charges). Verdict text on failure: `benchmark: +x% < buy-and-hold +y%`.
- `test_one` and the weekly run dispatch on horizon; a swing test needs no Upstox session.

## 4. Who builds them

- Weekly AI builder: one prompt per horizon; up to 3 intraday and 3 swing drafts per run, each
  shown its own vocabulary and its horizon's past drafts. The 5-active cap is per horizon.
- New strategy form and chat `propose_strategy`: a `Horizon` choice (Intraday / Swing);
  `GET /strategies/vocabulary` returns `{"intraday": {...}, "swing": {...}}`.
  Per-user limits: 3 submissions a day (shared), one testing at a time (shared), 5 active per
  horizon.
- Library, Mine and Tried-and-rejected show the horizon as a chip (`Intraday` / `Swing`).

## 5. Error handling

- A spec with unknown blocks for its horizon is cleaned or refused by the validator, as today.
- Missing daily bars for a symbol: that symbol is skipped in the backtest; fewer than 30 symbols
  with bars -> the draft stays `testing` with "waiting for market history".
- A test exception -> `rejected` "test failed: <error>" (as user strategies).

## 6. Testing

- Each swing block fires and stays quiet on crafted daily series; swing state matches batch
  indicators.
- Validator: horizon routing, long-only, required max hold, `swing_low` vs `atr_multiple`.
- BlockStrategy swing: one intent per 5 days per symbol; `max_hold_days` on the intent.
- Exits: max hold and trailing stop in `check_exits` and in the backtest.
- Checks: a strategy that passes the gate but trails buy-and-hold is rejected with the benchmark
  verdict; per-horizon trial counts.
- Scan: an active swing built strategy files a proposal for its owner only.
- API/form/chat: horizon in vocabulary, submit and cards.

## Out of scope

Earnings events (18.2); short selling; options; intraday changes; point-in-time index membership
(the buy-and-hold benchmark is the mitigation).
