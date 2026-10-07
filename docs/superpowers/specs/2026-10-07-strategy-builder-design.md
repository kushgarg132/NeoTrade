# Strategy builder: the AI drafts intraday strategies, the gates decide

User-approved design, 2026-10-07. Builds on the game plan and strategy library
(`2026-10-05-ai-game-plan-and-strategy-library-design.md`) and the backtest/paper gates.

## Intent

The daily game plan can only choose among the strategies that exist, and every one of
them fails its gate after charges (ROADMAP Phase 17). The owner wants the AI to build new
intraday strategies from what the plans keep wanting, which the plan and the autopilot can
then use, but only after they earn it with the same evidence every built-in needs.

Success: built strategies are drafted weekly, each is tested on a year of 5-minute history
with no manual step, and any that pass reach paper trading automatically and live trading
only through both gates. Nothing becomes less safe than today.

### Decisions (from the brainstorm)

| Question | Decision |
|---|---|
| What the builder does | **AI proposes, gate decides.** The AI drafts strategies; a year-long backtest admits or rejects each. |
| Path to real money | **Paper, then both gates.** A passing draft trades paper at once; live only after it also earns the paper record. |
| Cadence | **Weekly, up to 3 drafts.** |
| Representation | **Block spec + one interpreter.** The AI writes JSON from a closed vocabulary; it never writes code. |
| Scope | Global: one set of built strategies for every user, each judged on that user's own paper record. |

### Invariants (never broken by anything below)

1. The AI never places or sizes an order. It writes a spec; a spec trades only after it
   passes the gate below, and live only after the paper gate as well.
2. No model output is executed as code. A spec is data, read by one tested interpreter.
3. The game plan still only tightens. A built strategy enters the library as a member the
   plan may `allow`; the plan gains no new lever.
4. `composite.py` stays the only conviction formula (`AI_CAP`, `RULE_FLOOR` unchanged).
   Built strategies emit `Intent`s with non-empty `reason_codes`, scored like any other.
5. Kill switch, autopilot fence, trading limits, learned rules, backtest gate and paper
   gate apply to built strategies exactly as to built-ins.
6. `backend/strategies/` stays I/O-free and wall-clock-free (existing tests enforce it).

## 1. Block vocabulary

A spec is one setup, zero to three filters, a side, and exits. Every number is clamped to
its range by the validator; a value outside it is clamped, an unknown key is dropped.

| Kind | Block | Parameters (range) |
|---|---|---|
| Setup (exactly 1) | `orb_break` | `range_minutes` 5–30 |
| | `gap` | `direction` up/down, `min_pct` 0.5–4.0 |
| | `vwap_cross` | `mode` reclaim/lose |
| | `rsi_cross` | `period` 7–21, `level` 20–80, `direction` up/down |
| | `ema_pullback` | `period` 9–50 (trend side follows `side`) |
| | `volume_spike` | `multiple` 1.5–5.0 of the 20-bar average |
| Filters (0–3, distinct) | `time_window` | `start` ≥ 09:20, `end` ≤ 14:45 IST |
| | `regime_is` | subset of `risk_on`, `neutral`, `risk_off` |
| | `sector_rs` | `min` −3.0–3.0 (% sector vs Nifty today) |
| | `atr_pct` | `min` 0.3–3.0, `max` 0.5–6.0 |
| | `price_vs_vwap` | above/below |
| | `volume_confirm` | `multiple` 1.2–3.0 |
| Side | `side` | long / short (short is MIS intraday only) |
| Exits (stop and target required) | `stop` | `atr_multiple` 0.5–3.0, or `setup_bar` |
| | `target` | `r_multiple` 1.0–4.0 |
| | `time_stop` | `minutes` 15–240 (optional) |

The 15:15 square-off always applies. A spec without a stop or target is refused.

Example: `{"setup": {"gap": {"direction": "down", "min_pct": 1.0}}, "filters":
{"price_vs_vwap": "above", "volume_confirm": {"multiple": 2.0}, "time_window":
{"start": "09:30", "end": "14:45"}}, "side": "long", "stop": {"atr_multiple": 1.0},
"target": {"r_multiple": 2.0}}`, rendered as "Long when the stock gapped down at least
1% and is back above VWAP on 2× volume, 9:30 AM–2:45 PM; stop 1× ATR, target 2R."

## 2. Code units

- `backend/strategies/blocks/`: one pure function per block over a rolling per-symbol
  state (`state.py`) that updates ATR, VWAP, EMA, RSI, the opening range, the 20-bar
  volume average and the day's gap **incrementally per bar**, never recomputing from the
  history. Target ≥ 1,000 bars/s, so a year on 75 symbols (~1.4M bars) runs in about 25
  minutes (the built-ins run ~125 bars/s).
- `backend/strategies/built.py`: `BlockStrategy(spec, slug, universe, symbol_for_token,
  params)`, a `TokenResolvingStrategy`. `PARAMS` are the spec's numbers flattened
  (`setup.gap.min_pct`, …); `GRID` is one step either side of each, so the monthly
  re-tune covers it. `CARD` is derived from its blocks (style from the setup, `regimes`
  from `regime_is` or all three). Intents carry `reason_codes` `["built:<slug>", <setup>,
  <each filter>]`.
- `backend/builder/validate.py`: pure. Parses the model's JSON (`_extract_json`), drops
  unknown blocks and keys, clamps numbers, refuses a spec with no setup, stop or target,
  and refuses a duplicate: same setup, filters and side as an active or tested spec, with
  every number within one grid step. Also `describe(spec) -> str` (the plain sentence).
- `backend/builder/draft.py`: the weekly job (section 3). `python -m backend.builder`.
- `backend/builder/store.py`: collection `built_strategies`, one document per draft:
  `slug`, `spec`, `thesis`, `drafted_at`, `status` (`testing`, `rejected`, `active`,
  `retired`), `verdict` (reason), `metrics` (full year and holdout), `trials` (count used
  for the Deflated Sharpe).
- `backend/prompts/strategy_builder.md`: system prompt plus the vocabulary table, the
  inputs below as `{{placeholders}}`, and the output schema (≤ 3 specs, each with a
  `thesis` line). Feature key `learning` (OmniRoute per-feature metering).

## 3. Weekly flow

Friday's 16:00 pass starts `nice python -m backend.builder` as its own process, as the
first pass of a month already starts the re-tune, so the trading day never waits on it.
It runs overnight, one draft at a time, under a Redis lock so two never overlap.

1. **Inputs** (through `backend/ai/facts/`, never raw collection reads in the prompt):
   the week's plans (`allow`, `rationale`, `skip_day`), `plan_scorecards`, the library
   cards with gate results, attribution's worst setups across users, and every earlier
   draft with its spec, verdict and metrics, so it does not repeat a failure.
2. **Draft:** one deep-tier call; up to 3 specs. Each passes `validate`; the rest are
   stored `rejected` with the reason.
3. **Test** each valid spec, `status=testing`: a year of 5-minute history from the
   admin's Upstox session (`risk/gate_backtest.py::intraday_history`; no Upstox session
   means no test, drafts stay `testing` for next week), on the default universe, net of
   charges and 10 bps slippage per side, at the admin's `account_size` and
   `per_trade_cap`.
4. **Pass needs all three:**
   - the existing gate (`risk/backtest_gate.py::passes_gate`: ≥ 365 days, ≥ 30 trades,
     PF ≥ 1.3, max DD ≤ 15%);
   - the last 3 months alone net-positive after charges (a holdout: the AI saw recent
     weeks through the plans);
   - Deflated Sharpe ≥ `MIN_DSR` (0.95) counting every draft ever tested
     (`factor/validate.py::deflated_sharpe`, the re-tune's guard).
5. **Record:** the gate row goes to `strategy_backtests` under `built:<slug>` (so the
   library and both gates read it unchanged); the draft gets its verdict.
6. **Notify** the admin once: "3 drafted, 1 passed: built:gap-down-vwap-reclaim (PF 1.41,
   312 trades, holdout +₹2,140)."

## 4. Path to trading

- **Active:** a passing draft becomes `active`. `build_default_strategies` loads every
  active spec as a `BlockStrategy` at each run start, so the next intraday run (auto or
  manual) paper-trades it for every user, and the game plan sees its card and may
  `allow` it per stock.
- **Live:** unchanged paths, unchanged gates. The user may switch it live in Practice ›
  Setup, and the autopilot in Live mode takes its orders, only once it has also earned
  the user's paper record (20 trading days, 30 trades, net profit, PF 1.3, DD within 5%)
  (`engine/autorun.py::_proven_strategies`, `risk/paper_gate.py`).
- **Learning:** the nightly loop pauses a built strategy that loses over ≥ 30 trades, as
  any other.
- **Retire:** paused for 30 days, or a later re-test fails, sets `retired`: still listed,
  never loaded.
- **Cap:** at most 5 `active`. A sixth pass retires the active one with the lowest paper
  net across users (ties: oldest).

## 5. Surfaces

- Practice › Strategies lists built strategies with a "Built" badge, the plain sentence
  from `describe`, the thesis, the year and holdout results, and the paper record.
  Rejected drafts are folded under "Tried and rejected" with their reason.
- Handbook Jobs panel: the builder's last run, and an admin "Run now" button
  (`POST /system/builder/run`).
- Chat tool `get_built_strategies` (read-only, through `ai/facts`).

## 6. Error handling

- LLM failure, invalid JSON, or the feature switched off on the handbook AI panel: the
  run records "no drafts" and exits; nothing else changes.
- Backtest failure on one draft (history gap, timeout): that draft stays `testing` and is
  retried next week; the others continue.
- A spec that fails to load at run start (vocabulary changed since): skipped with a
  warning; the run starts without it.

## 7. Testing

- Each block on synthetic bars: fires and stays quiet where it should.
- Incremental state matches the batch indicators in `components/quant/indicators.py`
  on the same series.
- `validate`: unknown blocks dropped, numbers clamped, no-stop and duplicate refused.
- `BlockStrategy`: the example spec fires once on a crafted gap-down-and-reclaim day,
  with the reason codes above; a time stop and the square-off close it.
- Draft job with a stubbed LLM and a stubbed backtest: pass, gate fail, holdout fail,
  Deflated Sharpe fail, duplicate, cap reached.
- Registry loads only `active` specs, and a broken spec is skipped.
- Throughput: ≥ 1,000 bars/s on a synthetic 50k-bar run.
- The existing I/O-free test covers `backend/strategies/blocks/` and `built.py`.

## Out of scope

Options blocks; multi-leg or pairs strategies; AI-drafted long-term (daily-bar)
strategies; per-user drafts; letting the plan or the autopilot create a strategy
mid-session.
