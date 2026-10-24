# Trading-edge audit, 2026-10-24

Repo `main` @ `c67db9b`; the deploy clone's backend matches it. This was a read-only audit run by four independent passes: the senior NSE trader, the senior developer, the architect, and a joint AI-layer pass. A debate and one plan follow the findings. Prod Mongo and Redis were read with find/count/aggregate/GET/SCAN only. The architect issued one `update_one` that could not match anything (`user_id="__none__"`, `upsert=False`) to time a write round trip. No backtest was run, because the gate backtest persists its rows. `pytest` ran in the py3.11 image with `--network none`: **2192 passed, 0 failed**.

Labels: **V** means verified (queried, reproduced or exact code read), **S** means suspected, **U** means unknown. Paths are relative to `backend/` unless stated otherwise.

Builds on, and does not repeat: `docs/audits/2026-10-08-functional-audit.md` (its status is in section 3.4), ROADMAP Phase 17, and P2.1/P2.2/P2.3 (the scorecard with MTM, 10 bps paper slippage, the cost-aware fence).

---

## 1. Executive summary

1. **No strategy has a gross edge that covers its friction.** 0 of 33 strategies pass the gate (51 `strategy_backtests` rows). Honest 1-year intraday rows show about +0.2 INR gross per round trip against 4.5-5.1 INR of charges, with PF 0.80-0.88. (V)
2. **At a 5,000 INR per-trade cap, friction is the strategy.** A CNC round trip costs 81 bps, of which the 15.93 INR depository (DP) charge is 32 bps. A MIS round trip costs 31 bps. The Picks study nets costs at 100k notional, so its edges are overstated by about 30 bps at live size. (V)
3. **Backtest and paper are different systems.** Stops, targets, trailing stops and max-hold exist only in `engine/backtest.py:68-146`, not in `engine/runner.py`. Paper fills at the signal bar's close or the 09:20 mark; the backtest fills at the next open. One reproduced trade (CANBK) differs on entry, quantity and exit. (V)
4. **The AI account trades the wrong things.** Picks enters only `pullback` (grade C, adjusted t=1.12) because `autopilot/picks.py:enter` ignores grade. The only setups with an edge, `momentum` (t=2.19) and `rs_leaders_regime` (t=2.67), are not what trades. `analyst_verdict` cannot be backtested, has closed 2 of 2 trades at a loss, and fires on a 0.15 label cliff. (V)
5. **Live record since the 2026-10-14 reset:** 13 trades. The 6 closed trades are 0 wins, -367.5 INR net. The 7 open trades are -368.9 INR MTM, on a 25k account. The sample is too small to judge, but it is consistent with points 1-4. (V)
6. **The evidence pipeline is silently broken.**
   - The intraday engine has not run since 2026-10-16 (Lab off). The heartbeat says ok.
   - News triage stalled from 10-20 to 10-23, leaving 7,423 items NEW and 2,778 FAILED that are never retried.
   - `market:brief` is 3.9 days old, has no TTL, and is served without an `as_of`.
   - No game plan has been built since 10-16.
   - No alert fired for any of this. (V)
7. **P&L math is gross in the places that stop losses.** `realized_pnl` is gross in the ledger (`engine/persistence.py:147,160`), so the kill switch and the autopilot loss trip ignore charges. The engine uses a 3× cost filter (`runner.py:75`), the fence 1.5× (`autopilot/fence.py:22`). (V)
8. **The universe is today's survivors:** 236 symbols, none delisted. Every Picks, factor, swing and RL number is biased upward. (V)
9. **Live readiness: no gate is fully met.** There is no broker-side idempotency tag, reconciliation is observation-only, the kill switch blocks entries but flattens nothing, and no live order has ever been placed in prod. (V)

**Plan in one line:** stop trading setups without an edge, make paper run the same exits and fills as the backtest, fix the net-of-cost numbers, and alert when the engine or news goes quiet. Then re-validate everything under a significance gate at the size actually traded. Real money stays off until P3.

---

## 2. Strategy scorecard

Sources: the latest `strategy_backtests` row per strategy, with round trips rebuilt from fills. The account is assumed at 25k, with honest sizing unless the row is marked STALE. `paper_trades` covers the live record, `picks_study.latest` the Picks setups. Sharpe uses only days with a trade (finding T8), so it is not comparable to a fully invested Sharpe. The trader's full table, including the regime split, is reproduced in the appendix.

| Strategy | n (rt) | Win | Exp INR/rt | PF | Net INR | Gross/rt vs charges/rt | Regime | Verdict | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| trend_day_pullback | 2255 | .41 | -4.6 | .85 | -10,325 | +0.2 vs 4.9 | negative in all 4 regime cells | **KILL** | zero gross edge, highest turnover |
| gap_fill_fade | 1070 | .46 | -4.6 | .87 | -4,944 | +1.0 vs 5.1 | negative in all 4 | **KILL** | |
| relative_strength_sector | 341 | .43 | -9.0 | .88 | -3,062 | +0.7 vs 9.0 | negative in all 4 | **KILL** | |
| technical_breakout (1d) | 94 | .40 | -40.8 | .61 | -3,833 | -17 vs 23 | only vol_hi breaks even (n=43, PF 1.01) | **KILL** | negative gross; 2 of 2 closed paper trades lost |
| macd_crossover (1d) | 92 | .27 | -32.6 | .56 | -3,003 | +11 vs 28.5 | negative in all 4 | **KILL** | 1 of 1 closed paper trade lost |
| mean_reversion (1d) | 65 | .48 | -48.1 | .60 | -3,124 | -6.6 vs 21 | negative in all 4 | **KILL** | |
| built:* intraday (orb-break, vwap-cross, rsi-cross ×2, gap-up) | 789-1615 each | .42-.43 | -4.6 to -6.8 | .80-.88 | -4.2k to -8.8k each | about 0 vs 4.5-4.9 | negative | **KILL** | all 22 AI-drafted strategies fail |
| built:swing-* (20d-breakout, rsi2-dip, gap-hold, vol-breakout) | 81-413 | .40-.46 | -26 to -41 | .63-.74 | -3.3k to -10.8k | negative | 3-year window is about 98% trend_up, so it is untested in down markets | **KILL** | |
| built:gap-up/down-volume-confirm, ema-pullback-atr-pct | 5-17 | | | | ±90 | | | **no information** | n too small; do not fund |
| orb_breakout, volume_surge, vwap_reversion, rsi_momentum_scalp | 41-183 | | | | | | | **UNKNOWN, re-run** | latest rows are STALE (10-04: 60 days, 1M INR sizing, 23-38× turnover per day); never re-run under the honest backtester |
| gap_and_go | 0 | | | | | | | **FIX the backtest** | `risk/gate_backtest.py:109-118` passes no `prev_closes`, so it can never fire in a backtest; 1 paper trade (-16.6) |
| analyst_verdict | no backtest | 0 of 2 closed | | | -157.7 closed, -235.8 open | | | **PARK** (no autopilot entries) | an LLM-label entry at a ±0.15 cliff over a 30-day impact window; cannot be replayed |
| quality_momentum, factor book | no row / 100% cash since 10-15 | | | | | | | **UNKNOWN** | factor out-of-sample verdict not stored in `lab_runs` |
| **Picks: momentum** (20d) | 2,779 events | p_up .545 | adjusted excess +0.74% | | | 100k-notional costs | | **KEEP on probation** | t=2.19; re-net at the 5k cap |
| **Picks: rs_leaders_regime** (60d, experimental) | 1,211 | .588 | +2.89% | | | | | **KEEP, forward-test, then scale** | t=2.67; overlapping windows inflate t (S) |
| Picks: pullback (20d) | 3,090 | .556 | +0.36%, median about 0 | | | | | **KILL from autopilot** | t=1.12, grade C; it is the only setup the AI account currently trades |
| Picks: momentum_vol_60, breakout_52w, low_vol | 1.2k-3.8k | | +0.42% / -2.53% / -1.78% | | | | | **KILL** | low_vol t=-2.33 is worse than the average stock |

Live paper record (all 13 trades since the reset): 6 closed, 0 wins, gross -257.0, charges 110.5, **net -367.5**; 7 open at -368.9 MTM. `paper_gate` needs 30 trades and 20 days, so no strategy is near eligible.

---

## 3. Findings per persona

Severity: **P0** means the numbers are invalid or real money can be lost. **P1** means a material effect on edge or risk. **P2** means hygiene with some edge impact. **P3** is minor. Each persona's full report, including every file:line, was kept as working notes. The findings that matter are reproduced here.

### 3.1 Senior NSE trader

| ID | Sev | Where | Evidence | Impact on edge | Fix | |
|---|---|---|---|---|---|---|
| T1 | P0 | `strategy_backtests`, `risk/backtest_gate.py` | The 4 classic intraday strategies have only STALE rows (1M INR sizing, 60 days) | The strategies the auto-run uses have no valid evidence | Re-run them on Upstox 1-year data at the 25k prefs; mark the old rows invalid | V |
| T2 | P0 | `engine/runner.py` (no equity exits) vs `engine/backtest.py:70-140` | `levels` is defined only in `backtest.py`. RELIANCE `gap_and_go` touched its stop (1205.4) and rode to the 15:15 square-off | The backtest measures a stop-managed system that paper does not run | Move the exit engine into `run()` (see D-C1 / A-F2) | V |
| T3 | P1 | `autopilot/picks.py:344-382`, `forecast/picks.py:116` | `enter` ignores `grade`. All 8 live picks are pullback. The pick doc's `edge: true` comes from `walk_forward`, not `adjusted`. The ranking key is about -2e-7 | The AI sleeve trades a setup with no edge, labelled as having one | Enter grade A only; take `edge` from `adjusted.edge`; rank by adjusted excess | V |
| T4 | P1 | `engine/execution/costs.py:72-102`, `fence.py:43-49` | CNC 81 bps and MIS 31 bps at 5k; DP charge is 32 bps at 5k | Positions this small cannot clear fixed costs | Set a minimum viable notional per trade and concentrate into fewer, larger positions (owner question Q2) | V |
| T5 | P1 | `costs.py:61,86` | CNC brokerage is modelled as `min(20, 0.03%)`; Kite delivery brokerage is zero by its published schedule | It overstates about 15 INR per 5k round trip, which may move T4 | Use broker-specific schedules, calibrated against one real contract note (`journal_trades` has 54) | S |
| T6 | P1 | `forecast/study.py::NOTIONAL`, `lab/assumptions.py:28` | The study nets costs at 100k; the live cap is 5k | Net edge is about 30 bps too high per CNC round trip | Parametrise notional to the account's cap and show both | V |
| T7 | P1 | `daily_bars`, `factor/nifty200.csv` | 236 symbols, 0 delisted; the RL runs' "best hold about 120 days" looks like drift | Every Picks, factor and RL number is biased up | Use point-in-time Nifty-200/500 membership and keep delisted names' bars | V / S (size) |
| T8 | P1 | `engine/metrics.py:20-21,52,62-70` | Entry fills are counted as P&L events (`-costs`); Sharpe skips days with no trade; drawdown is realised only | Sharpe is not comparable across strategies; drawdown is understated | Compute metrics from a daily MTM equity series that includes zero days | V |
| T9 | P1 | `risk/backtest_gate.py` (n≥30, PF≥1.3, DD≤15%) | A zero-edge strategy passes often at n=30. With 22 AI drafts plus monthly retunes, the trial count is large | A lucky run can pass the gate | Require t≥2 on net expectancy, n≥100, positive in ≥2 regimes, an OOS window, and deflation by trial count (reuse `factor/validate.py::deflated_sharpe`) | S |
| T10 | P1 | `analytics.py:65-103`, `routers/trading.py:452-455`, `autopilot/service.py:123` | Paper `realized_pnl` is gross | Loss limits trip late by the charges; a net loser can be shown as a win | Store `net_pnl` on `paper_trades` and read it everywhere | V |
| T11 | P1 | `engine/autorun.py:424-434` | The drift guard checks upward drift only. BHEL was re-bought 4.7% under the idea a day after its stop | It buys falling knives and repeats a name that just invalidated its own thesis | Add a downward-drift refusal and an N-session cooldown per symbol after a stop | V |
| T12 | P1 | `autopilot/fence.py:58-112` | No sector, correlation or weekly cap. Daily limit is 1,000 INR, which is 4% of 25k | A 3-day losing streak is 12% | Daily limit 1% while unproven; add a weekly limit and a sector cap | V |
| T13 | P2 | prefs `auto_paper_intraday: true`; last INTRADAY run 10-16 | 1 intraday paper trade in total | Intraday evidence can never accrue | Decide formally: park intraday until T1 is re-run (debate D1) | V |
| T14 | P2 | grep finds nothing | No circuit limits, auction, ASM/GSM, T2T or ADV floor | Fills are assumed at band-limited prices | Add a price-band flag and an ADV floor in the universe builder | V (absent) |
| T15 | P2 | `datalayer/bars.py:88` | Daily bars are adjusted; 5m bars are not (S); `prev_closes` come from the daily bars | Fake gaps appear on corporate-action days | Cross-check the daily close against the 5m close; drop symbol-days that differ by more than 1% | S |
| T16 | P2 | `backtest.py` (PF=0 when there are no losers) vs `paper_gate.py:39-45` (None passes) | Opposite conventions | A flawless small sample fails one gate and passes the other | Use one convention | V |
| T17 | P2 | `suggestions`, `fence.py:52-55` | 12 of 19 engine proposals were refused as outside Nifty 200 | Forward records and paper cover different universes | Use one universe (A-S8) | V |

**What a professional analyst would demand from Picks.**
- **Exists today:** walk-forward with a same-month baseline and month-block bootstrap t, which is the strongest part of the stack. Also `lab_runs` reproducibility (fingerprint, `code_sha`).
- **Partly exists:**
  - hit rate and expectancy, but only at 100k notional;
  - multiple-testing control, with no deflation applied;
  - holding-period decay;
  - a regime table;
  - a corporate-action-clean data vendor.
- **Missing:**
  - a point-in-time universe;
  - MAE/MFE;
  - capacity and ADV;
  - basket correlation and sector concentration;
  - any scored forward record (0 of 52 picks scored; the first is due 2026-11-19);
  - a confidence-vs-outcome calibration with data.

Verdict: `momentum` and `rs_leaders_regime` could be sold as a research screen with their caveats shown. The graded list as it stands could not.

**Compliance (no RA; Picks admin-only).**
- **What is clean:**
  - `routers/picks.py` is admin-only.
  - `autopilot/picks.py:_admin` gates Picks entries.
  - Nothing about Picks reaches Telegram.
  - No feature publishes Picks to non-admin users.
- **Watch item W1, `/suggestions`:** any Google account can sign in with role `user` (`auth/store.py:17`). `/suggestions` is gated only by `get_current_user` (`server.py:260`), so it serves engine buy ideas with entry, stop, target and an AI thesis to any signed-in user. The Telegram text "N idea(s) for your account" works the same way.
  - `PRODUCT.md` treats engine suggestions on the user's own account as a free tool, which is fine for the single owner.
  - It becomes the line the 2026-10-18 decision draws the moment a second user signs in (Phase 12 beta). The fix is owner question Q4. (V)
- **Watch item W2:** approve-live and chat orders on the owner's own `mine` account are fine for self-use.

### 3.2 Senior software developer

**Deletions first.** About 1,470 lines of code have no production importer (V, AST import scan):

| What | Where | Lines |
|---|---|---|
| One-off research tools | `forecast/research/{bandit_experiment,new_setups,perstock_experiment}_tool.py` | 871 |
| RL harness | `rl/` (first run failed 0/5, nothing wired) | about 336, plus 3 tests |
| ML harness | `ml/` (failed its bar, nothing wired) | about 262, plus 2 tests, plus `lightgbm==4.6.0` in `requirements.txt:35` |
| Survivorship CLI | `factor/survivorship.py` (one-off; its result is already in the ROADMAP) | 63 |
| Empty collection | `paper_limit_orders` index at `server.py:147` (0 docs; nothing reads it) | |
| Old build images | 18 `neotrade-verify-*` Docker images on the host, with disk at 92% | |

**Duplicate implementations**

| Concern | Copies | Fix |
|---|---|---|
| Cost-vs-gain entry filter | `runner.py:75` (3×) and `fence.py:22` (1.5×) | One function and one named constant per path |
| Friction composition (charges plus slippage) | `runner.py:308-314`, `fence.py:43-50`, `lab/assumptions.py:28-34`, `builder/draft.py:301`, `journal/mirror.py:36-39`, `portfolio/rebalance.py:121-123`, `factor/paper.py:145`, `factor/backtest.py:118` | One `round_trip_cost` in `lab/assumptions.py` |
| ATR, 5 definitions | `strategies/indicators.py:33-39`, `strategies/blocks/state.py:55-60`, `forecast/picks.py:47-52`, **`ai/facts/market.py:44-52`** (labels mean(high−low) as `atr_14`), `backtest.py:109` | One ATR function |
| Fill builders, 3 copies | `simulated.py:71-83`, `suggestions/service.py:49-72`, `broker.py:72-` | One `book_fill` |
| P&L round-trip builders, 5 copies | `portfolio.py:36`, `persistence.py:127`, `backtest.py:157-185`, `analytics.py:25`, `journal/roundtrips.py:73` | Consolidate onto one |
| Session windows | `autorun.py:49` (09:15-15:30) vs `guardrails/monitor.py:52` (15:35 inclusive) | One window (still open from the 10-08 audit, item 14) |

| ID | Sev | Where | Evidence | Impact | Fix | |
|---|---|---|---|---|---|---|
| D-C1 | P0 (raised from P1; same as T2/A-F2) | `engine/backtest.py:68-146` vs `runner.py` | Exits exist only in the backtest wrapper | Gate 1 and Gate 2 measure different systems | Move `levels`/`exit_at_level` into `run()`; delete the `submit` monkeypatch | V |
| D-C2 | P1 | `engine/portfolio.py:36-62`; the kill switch in `runner.py` | `Portfolio.equity()` is gross; `fill.costs` never reaches `realized_pnl` | The kill switch trips late | Add `costs_paid` to `Portfolio` (one line in `apply`) | V |
| D-C3 | P2 | `risk/rules.py:17-24` | A BUY with its stop above entry is sized as a short | Bad specs size silently | Reject a stop on the wrong side in `size_intents` | V |
| D-C4 | P2 | `runner.py:269-281` | Sizing uses the close; fills land at the next open or the mark plus 10 bps | Realised risk is above the nominal 1% | Size on the expected fill price | V |
| D-C5 | P2 | `scoring/composite.py:27-34`, `runner.py:276` | Sentiment scales risk by ±26% at rule 0.6 (±43% at 0.5). Backtests run with `redis=None`, so AI=0 there | AI sizing cannot be replayed; backtest and paper size differently | Debate D3 | V |
| D-C6 | P1 for live | `execution/broker.py:45-57` | The broker order is placed before the row is recorded; there is no broker tag | A crash between the two causes a double send on retry | Write a SUBMITTING row first and pass `order.id` as the broker `tag` | V (code) |
| D-C8 | P2 | `suggestions/exits.py:44-47` | `busday_count` is called without NSE holidays | `max_hold` fires early after holidays | Pass `holidays=HOLIDAYS` | V |
| D-C10 | P2 | `engine/session.py:23-26` | Square-off is keyed off the bar timestamp; a run that receives no bars never squares off | MIS positions can be left overnight | Add a wall-clock backstop in `autorun.tick` | V |
| D-C11 | P2 | `jobs.py:35-45` | All loops and engine runs share one asyncio loop; per-bar pandas runs in the strategies | Can starve the heartbeat | Add a bar-latency metric first | S |
| D-T1 | P1 | `backend/tests` (249 files) | No golden-trade or backtest-vs-paper parity test | This is why D-C1 went unseen | One fixture that runs through both paths and asserts the exact net in rupees | V |
| D-V1 | P1 | `runner.py` `size_intents` | Rejections are only `logger.info`; only `below_cost` is counted | A trader cannot see why a signal did not trade | `signal_log` rows: symbol, strategy, strength, outcome, reason | V |
| D-V2 | P2 | `costs.py`, fills | Costs are stored as one lump; slippage is baked into the fill price | No per-trade cost breakdown | Return a cost dict and store `slippage_inr` | V |

Float money everywhere (D-C7) is not a P&L driver; round at persistence boundaries only. No path was found where raw LLM text becomes an order quantity or price.

### 3.3 Architect

The real data flow (V):

```
 [ingest] yfinance quotes -> Redis quote:*   Yahoo/Upstox daily -> Mongo daily_bars (only candle store)
          news -> triage(fast) -> score(deep) -> news_items -> sentiment:{SYM}, market:brief, regime
                                         |
 [jobs] autorun.tick (60 s, gated by Lab + live feed) -> build_feed (Kite/Upstox ticks | yfinance poll)
                                         v
        engine/runner.py::run  -- strategy.on_bar -> Intent -> size_intents (composite, plan gate, kill switch,
                                  RiskRules, cap, 3x cost filter) -> Order
           |  exits: 15:15 square-off ONLY  (no stops/targets)          <-- divergence D1
           v
        paper: SimulatedExecutionClient fills at signal-bar CLOSE       <-- divergence D2
        live : AutopilotExecutionClient -> fence.check -> broker (0 live orders ever)
           v
        Portfolio (gross) -> ledger -> paper_orders/fills/trades (realized_pnl gross)

 [daily] suggestions/scan.py -> run() (same core) -> suggestions -> fence (1.5x) -> fill_on_paper @ 09:20 mark
           exits: suggestions/exits.py on a 15-min mark poll                <-- 12 of 13 paper trades took this path

 [backtest] gate_backtest -> run_backtest: run() + exit wrapper (backtest.py:76-129), fill at next OPEN,
            Upstox 5m refetched each run (~975 calls), no prev_closes, redis=None (AI=0, no plan)
```

**Verdict:** `run()` plus `size_intents` is one shared core for signals and sizing. It stops being shared at fills and exits. LONGTERM paper, where 12 of the 13 trades happened, bypasses `run()` for execution.

| ID | Sev | Where | Evidence | Impact | Fix | |
|---|---|---|---|---|---|---|
| A-F1 | P0 | `engine/autorun.py:209-210,508`; `system/data_quality.py:134-140` | Lab is off (no `lab_enabled` key) and the heartbeat reports ok=1 with "started 0". No run since 10-16. Nothing checks the engine | 5+ sessions of intraday evidence lost silently. It probably also explains no plan since 10-16 (the plan build is `lab_on`-gated; S) | Add to `data_quality.live()`: a trading day with `auto_paper_intraday` on and no run, or bars older than 15 min, fails the check. Also report a deliberate Lab-off as its own line | V |
| A-F2 | P0 | = T2 / D-C1 | | | | V |
| A-D2/D10 | P1 | `routers/trading.py:425`, `simulated.py:59-62`, `suggestions/service.py:49` | CANBK, GAIL and EXIDEIND entries landed 0.8-3.5% under the backtest's open fill | Paper cannot validate the backtest | Fill paper at the next open; re-confirm the signal price at entry | V |
| A-D5 | P1 | `risk/gate_backtest.py:109-118` vs `routers/trading.py:375-380` | No `prev_closes` in the backtest, so `gap_and_go` has 0 trades | The gate cannot gate it | Pass the same inputs; fail the gate on 0 trades | V |
| A-D6/F3 | P1 | `orb_breakout.py:50-59`, `plan/expand.py:44-57`; deploy workflow | No tick-feed backfill on start; 10 runs orphaned on 10-07 and 10-15; deploys have no market-hours guard | Signals after a restart differ from the backtest | Backfill history on `run()` start; block in-hours deploys in the shared workflow | V |
| A-F4 | P1 | `jobs.py:35-42`, `server.py:288-305` | The alert watcher runs in the same process as autorun | A hang of `neotrade-jobs` is silent | External probe on `/health` (cron + Telegram) or a Docker healthcheck | V |
| A-G7 | P1 | `data/feeds/tick_bars.py:100-110` | A dead feed emits flat zero-volume bars | A dead feed looks like a quiet market | Check last-tick age; stop the run when stale | V (code) |
| A-G3 | P1 for live | `engine/broker_recon.py`, `scheduler.py:211-224` | 5 of the last 8 recons are `not_checked: logged out`; no consumer gates orders on the result | Drift goes unseen until the next day | Gate entries on the last recon; check the broker position before entry | V |
| A-D7 | P2 | `tick_bars.py:78-84` | The first window's volume is 0 | Volume-gated strategies see different inputs live | Seed the baseline from history | V |
| A-F8 | P2 | compose logging | Only 3 hours of logs survive a recreate (open item 6 from 10-08) | Past runs cannot be diagnosed (the news stall cause is unknown because of this) | Host-mounted logs or journald | V |
| A-F9 | P2 | host | Disk 92% full (3.6 GB free); no memory limits | Builds and deploys can fail | Prune the `neotrade-verify-*` images; build one image for 3 commands | V |
| A-F10 | P2 | `runner.py:561,609,671` | Per-bar `snapshot_positions` and `is_tripped` calls | Can overwrite an autopilot `paper_positions` row (S) | Write positions on fills only | S |
| A-R1 | P2 | `REDIS_URL` uses `redis://` to a public host | Locks and broker access tokens may travel without TLS | Token exposure | Switch to `rediss://` after confirming the provider supports it | S |
| A-Data1/2 | P2 | `bars.py:31,195-205` | Weekly full re-pull; whether broker daily bars are adjusted is unknown; no split/bonus table | Series seam for up to 7 days after a split | Detect a split by ratio jump and force a full pull | S |
| A-Data3 | P3 | `daily_bars` | GOLDBEES 2019-12 artifact (-99%/+9900%); 18 OHLC-inconsistent bars | Noise | Sanity filter on write | V |

**Index lists (V):**
- `daily_bars` has only a unique (symbol, date) index. A query by date is a COLLSCAN, which is fine at 845k docs.
- `autopilot_log` and `stock_health` have only `_id`.
- The `paper_trades` indexes exist; the wiki's claim that it has no index is stale.
- Mongo and Redis round trips are about 2 ms, so I/O latency is not a problem.

### 3.4 Status of the 2026-10-08 audit

- **Fixed:** items 1, 3, 4, 7, 10, 11 (by removal) and 15.
- **Partial:**
  - Item 5: `adopt.close_stale` exists, but there is no wall-clock backstop.
  - Item 12: stale bars are now flagged.
  - Item 13: the backend calendar is done, but `frontend/src/utils/formatters.js:94` still says holidays are not modelled.
- **Open:**
  - Item 2: there is no broker-side stop on live approvals.
  - Item 6: logs are lost on every recreate.
  - Item 14: the session windows still disagree.
  - Item 16: the kill-switch text still says "live" only (`routers/today.py:95`).
  - Item 18: the `live_kite.py` docstring is still wrong.
- **Not rechecked:** items 8, 9, 17 and 19.

---

## 4. AI layer (Phase 1b, joint)

### 4.1 Call-site inventory (24 sites; estimates are labelled "est")

| # | Feature, tier, trigger | file:line | Budget | Inputs | Output and validation | Cache | Stored, read by | Failure | Calls/day, tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1 | News triage, fast, S | `datalayer/news.py:239,279-296` | none | NEW `news_items` titles | `_Triages` pydantic via `_ask`, one retry | none | `news_items`; every news consumer | 3 bad replies end in a terminal FAILED | est about 30; about 8k |
| 2 | News scoring, deep, S | `datalayer/news.py:244,352-373` | NEWS 200 | triaged items, 400 chars each | `_Scores` + `valid_impacts` | none | `news_items.impacts` | FAILED is never retried; items left out of a reply are stored as `impacts=[]` | real: 16/14/16 (stall days); normal est 28-31; about 9k |
| 3 | Sentiment aggregate (no LLM) | `datalayer/news.py:402-431` | n/a | 60-day impacts, 0.6/0.25/0.15 blend | float | `sentiment:{SYM}` 24 h | runner sizing, plan, analyst, facts | absent key reads as 0 | 0 |
| 4 | Market brief, standard, S | `datalayer/market.py:206,219-253` | not counted | top 25 items, macro, flows, regime | free text, no grounding | `market:brief`, **no TTL** | `backdrop()`: plan, analyst, chat, Home | keeps the old brief forever | est 3-10; 2.5k |
| 5 | Analyst news score, deep, U/S | `ai/analyst.py:95` | user `_charge` | top 5 Google News articles | `_NewsScores`, **all fields default** | `analyst:{SYM}` 4 h | note + `sentiment:{SYM}` | **a failure becomes sentiment 0.0, cached** | est 0-5; 4.5k |
| 6 | Analyst note + thesis, standard | `ai/analyst.py:128`, `datalayer/analysis.py:112` | user | stored news, sentiment, brief | text split on `===THESIS===`, no grounding | `analyst:{SYM}` 4 h, basis `item:sentiment.2f` | Research page, theses, review | "Unable to generate summary." is cached for 4 h | est 5-25; 4k |
| 7 | Analyst verdict refresh, S | `scheduler.py:417-430`, `ai/analyst_verdict.py:38-72` | none | rows 5/6 | label cut at ±0.15 | `analyst_verdict:{SYM}` 25 h | **`analyst_verdict` entry signal** | swallowed | est 10-20 |
| 8 | Suggestion thesis, S/U | `suggestions/thesis.py:35-80` | **not billed** | ResearchAgent | thesis text; `_rescored` | analyst 4 h | `suggestions.ai_thesis/score` | `_rescored` takes a failed 0.0 as real | est ≤8 |
| 9 | Chat turn, deep, U (WS/Telegram) | `chat/agent.py:113,129-165`, `ws/routes.py:222-250`, `guardrails/telegram_bot.py:242` | USER 150, charged once per turn | own tools in `chat/tools.py:83-264` (**not the fact layer**) | text + propose-only cards | none | client, `chat_actions` | fixed message | real 3 / 2 per day; 10-30k |
| 10 | Chat follow-ups, fast | `chat/agent.py:92` | | last 2k chars | lines | none | stream | checked | ≤1 per turn |
| 11 | Index move, standard, U | `research/index_move.py:189` | | yfinance, headlines, peers | free text | 15 min to 6 h | Home, chat | `ExplanationUnavailable` | est ≤5 |
| 12 | Game plan build, deep tools, S | `plan/builder.py:45,158,206` | PLAN 100 | universe, sentiment, 18 h headlines, **brief (1,500 chars)**, flows | `PlanReply` → `validate` clamps, **`ground_rationale`** | per day/version | `trade_plans`, PlanGate, runner | `fallback_plan` | est about 5; **0 since 10-16** |
| 13 | Plan revision, deep tools, S | `plan/revise.py:138,162` | PLAN | plan, regime, positions | `PlanReply`; **`exits` allowed** | | new `trade_plans` version | current plan stands | ≤2 plans × 2-3 calls |
| 14 | Portfolio review, deep, S | `portfolio/review.py:72` | none | holdings, health, 3 headlines | regex + `json.loads`, **no in-band check, no grounding** | none | `portfolio_snapshots` | `{}` | est 1; 12k |
| 15 | Weekly learning note, standard | `learning/report.py:80` | | own stats | text, no grounding | | Telegram | checked | 0.14 |
| 16 | Strategy hypotheses, deep, monthly | `learning/hypotheses.py:81` | | grid, retunes | regex + json + bounds | | `strategy_hypotheses` | no in-band check (parse catches it) | 0.03 |
| 17 | Strategy builder draft, deep, weekly | `builder/draft.py:100,112-118` | | library, worst setups | regex + json, then backtested | | `built_strategies` | no in-band check | 0.14 |
| 18-20 | Summaries (day fast; holding fast; activity/weekly/habits standard) | `summaries/core.py:80`, `day.py:46`, `holding.py:49`, `activity.py:54`, `weekly.py:43`, `habits.py:38` | | account facts | **grounded**, keeps the last good one, 6 h backoff | NX claim | `ai_summaries` | `core.failed` | est about 15 total |
| 21 | Symbol resolve, fast | `instruments/resolve.py:47-61` | | candidates | exact match | none | memory | an outage is reported as "Ambiguous query" | <5 |
| 22 | Peers, **deep**, chat tool | `research/search.py:51` | | name | `json.loads`, not checked against the master | none | tool result | `[]` | <3 |
| 23 | Model test, admin | `routers/settings.py:676` | | fixed | bypasses `get_completion` | | | explicit | ~0 |
| 24 | Tool runner (for 12, 13) | `ai/runner.py:39-131` | | facts as tools | schema + one repair | | | falls back to a single call | |

Total today (est): about 105-120 calls/day (fast about 45, standard about 25, deep about 40), about 0.8-0.9M tokens/day. Dollar cost is **unknown**: tiers are OmniRoute aliases (`auto/best-reasoning`, `auto/gemini`) and the repo has no price table.

### 4.2 Inconsistency cases (evidence)

- **C1, the market view (V, real data at 2026-10-24 00:35 UTC).**
  - `market:brief` is stamped 2026-10-21 03:00 UTC, has TTL -1, and says "Nifty down 1.11% … FIIs sold a net Rs 1,149 cr on 19 Oct".
  - `market:flows` for 23 Oct shows FII **+887.65** cr.
  - `index_move:^NSEI` says Nifty closed **-0.54%**.
  - The plan, the analyst report and chat all read the brief through `backdrop()` / `ai/facts/market.py:117-130`, which carry no `as_of`.
- **C2, verdict vs live sentiment (V).**
  - SBIN: verdict +0.0512, live -0.0171 (the sign flipped).
  - LT +0.1541 is "bullish" while ICICIBANK +0.1496 is "neutral": a 0.0045 gap decides an entry.
  - `impact_score` is the maximum over a 30-day window, so a month-old item counts as "fresh, material".
- **C3, two producers of `sentiment:{SYM}` (V, code).** The ingest blend (60 days, company/sector/market) and analyst `_store` (5 Google articles, 30 days) write the same key with different meanings.
- **C5, chat vs analyst (S).** Chat uses its own news and price tools and has no sentiment or analyst-note tool. The spec's step "chat moved onto facts" is not what the code shows. No transcripts are stored, so this can't be shown in data.
- **C6/C7/C9:** the portfolio review notes, plan rationale, summaries and index move each write their own prose about the same names or the market.
- **C10, backtest vs paper (V).** The backtest has AI=0 and no plan gate; paper reads live sentiment and the plan.

### 4.3 Correctness and safety

- **Error strings returned in-band** (`"LLM_DISABLED"`, `"Error generating response…"`, `llm.py:148,168`).
  - Ten callers check for them.
  - `portfolio/review.py`, `learning/hypotheses.py`, `builder/draft.py` and `research/search.py` don't check; they are saved only because the downstream JSON parse fails.
  - `instruments/resolve.py` reports an outage as "Ambiguous query".
- **The dangerous case** is in `ai/analyst.py:95-104,168-181,230-246` and `suggestions/thesis.py:68-80`.
  - A failed score becomes sentiment 0.0, which is cached for 4 h and written to `sentiment:{SYM}`.
  - From there it feeds `size_intents`, indistinguishable from a real neutral reading.
  - `_NewsScores` also accepts `{}`. (V, code)
- **Grounding** is used only in plan rationale and summaries.
  - The analyst note, portfolio review, index move, brief, learning note, chat and thesis all state figures without a check.
  - The existing check drops the sign (`abs`) and only tests that a number appears somewhere in the facts. The headline "CRR hike to 99%" passed it and drove a plan exit for FEDERALBNK on 2026-10-12 (it did not execute).
- **Decision boundaries.**
  - AI never approves a trade: the rule floor, `AI_CAP` and the fence all hold.
  - AI does reach sizing and exits, though:
    1. Sentiment changes risk by about ±26%.
    2. The plan's `risk_multiplier` (0.25-1.0) scales risk.
    3. The plan's `allow` / `skip_day` decide which trades exist.
    4. **Plan `exits` become MARKET orders on paper** with only symbol and scope checks: no price or loss condition and no fence (`engine/runner.py:387-410,621-634`).
    5. The `analyst_verdict` entry signal itself comes from the LLM.
  - None of these is in the backtest.
- **Reproducibility: none.**
  - No prompt version, model, input hash, token count or latency is stored anywhere.
  - Tier aliases mean that even the model name is unknown.
  - The 14 plans, 197 suggestions and 5 verdict trades cannot be replayed.

### 4.4 Cost and efficiency

- **Duplicates:**
  - The market view is written 5 times: brief, index_move, plan rationale, summary_day and summary_activity.
  - Per-symbol opinions are written 5 times: note, verdict, thesis, review and plan.
  - Two news-scoring pipelines run on the same news.
- **Could be code:**
  - Strategy hypotheses: 2 of 3 are "grid midpoint".
  - Peers: `instrument_sectors` exists.
  - Resolve: rank exact and prefix matches first.
  - The deterministic prune should run **before** triage.
- **Wrong tier:** peers on deep. A per-user `omniroute_model` overrides every tier, including news scoring (`llm.py:199`).
- **Cache noise:** the analyst basis includes `sentiment:.2f`, so market-wide moves rebuild every note (S).
- **Budgets vs real use:**

  | Budget | Setting | Real counts | Notes |
  |---|---|---|---|
  | `USER_LLM_CALLS_PER_DAY` | 150 | 3, 2 | Undercounts: one charge per turn |
  | `NEWS_LLM_CALLS_PER_DAY` | 200 | 16, 14, 16 on the stall days | Normal est about 30 |
  | `PLAN_LLM_CALLS_PER_DAY` | 100 | none, no plan since 10-16 | Historical about 5/day |
  | `AI_TOOL_CALLS_PER_DAY` (from the spec) | none | | Never implemented |

  The caps are 7-15× real use, so a stall looks like under-use.
- **Waste:** 2,778 FAILED news items burnt an estimated ~60 fast and up to ~196 deep calls. Those items are lost.

### 4.5 Target architecture (extend `llm.py` + `prompts/`, no new service)

```
 news -> prune(code) -> triage(fast) -> score(deep, schema) -> news_items -> aggregate(code) -> ai/facts
                                  \                                                            |
                         llm.complete()  raises LLMError{disabled,budget,provider,parse}       v
                         schema (required fields) + one repair + grounded(signed)        ai_views (symbol | market/session)
                         prompt_id + prompt_sha + input_hash                             score+label (code, hysteresis 0.18/0.12)
                                  |                                                      as_of, call_id, LLM prose only on invalidation
                         llm_calls (1 row per call, TTL 90 d) <---- call_id ----------------+
                                                                                            |
             chat get_view() | plan seed rows | analyst/verdict | portfolio review | suggestions/Picks thesis | Telegram
                                     |
                        plan.validate -> PlanGate -> size_intents (composite cap) -> fence ; plan.exits need a price/loss condition
```

- **One output contract:**
  - `LLMService.complete()` raises typed `LLMError`.
  - `get_completion` stays as a wrapper that returns the old strings, so callers can migrate one at a time.
  - `schema=` must use required fields.
- **One call log:** `llm_calls` with feature, tier, call site, model requested and returned, prompt id and sha, input hash, tokens, latency and outcome. `call_id` is stored on plans, suggestions, summaries and `paper_trades.context`. A "calls vs 7-day mean" alert would have caught the 10-20 stall.
- **One canonical view:** `ai_views` per symbol and per market session.
  - The score and label are deterministic, with hysteresis, and carry an `as_of`.
  - The verdict, the sentiment cache, chat, plan, review and theses all derive from the view and never re-ask.
  - The brief becomes the market view, with a maximum age; a stale view is shown as "unavailable".
- **One invalidation rule:** a view goes stale on:
  - a new scored item with impact ≥6 on the symbol or its sector (a material item, for the market view);
  - a price move above 1.5× ATR since `as_of`;
  - a regime flip;
  - age above 24 h (symbol) or 4 h in session (market).

  Reuse the trigger function in `plan/revise.py:42-80`.

**Calls/day before and after (estimates).**

| | Calls/day | Deep | Tokens/day | Dollar cost |
|---|---|---|---|---|
| Before | about 105-120 | about 38-45 | about 0.8-0.9M | unknown |
| After | about 90-100 | about 34-38 | about 0.65-0.75M | unknown |

The gain is trust and auditability, not spend. Migration steps are folded into the roadmap below (P0-6/7, P1-9, P2-6/7).

---

## 5. Debate log

**D1. Intraday: re-run it, or park it?**
- Trader: no intraday strategy has a gross edge at 31 bps of friction. Stop spending engine time on it.
- Architect: four strategies have only stale rows, and the engine has been silently off since 10-16. Without a fair re-run the "no edge" claim is half unknown.
- Developer: a re-run is worthless until paper and backtest share exits and fills (D-C1), because otherwise the gate passes a system that paper never runs.
- **Decision:**
  1. Keep intraday parked in practice and leave Lab off.
  2. Fix D-C1/A-D2 first, then run one honest re-run of the 4 stale strategies plus `gap_and_go`.
  3. Kill any strategy that fails the new gate.
  - **Reason:** edge breaks the tie. Nothing intraday has shown gross edge. The re-run is cheap once the core is shared, and a re-run before that would be untrustworthy.

**D2. Gate Picks to grade A now, or consolidate first?**
- Trader: the AI account is buying grade C `pullback` today. That fix is a few lines.
- Developer: the cost model and the 100k-notional study also need fixing, or "grade A" is graded on the wrong costs.
- **Decision:** gate to grade A now (P0). Re-net the study at the 5k cap in P1 and let the grades move.
  - **Reason:** stopping a known loss stream does not wait on a refactor.

**D3. AI in sizing: keep it (with canonical views) or remove it?**
- AI pass: the ±26% sentiment scaling is bounded and could add value once views are consistent.
- Developer: the backtest runs with AI=0, so the AI term is unvalidated by construction, and an outage injects a fake 0.0.
- Trader: an unreplayable input is not edge until proven.
- **Decision:**
  - Stop the outage case immediately (never cache a failed score).
  - Record the AI term per trade via `call_id`.
  - Owner decision Q3: set the effective AI weight in sizing to 0 until stored sentiment history lets the backtest show the term adds edge. This means changing `composite.py`'s blend, which is an invariant the owner has to approve.
  - **Reason:** unvalidated sizing inputs contaminate every paper result.

**D4. Add a `candles_5m` store, or not (architect's one "add")?**
- Architect: backtests refetch about 975 Upstox calls per run and can't be repeated, and the parity test needs a fixture.
- Developer (ponytail): no new storage unless it deletes something.
- **Decision:** add it, written by the tick aggregator and by the first backtest download.
  - **Reason:** it removes the per-run Upstox dependency, makes the gate repeatable, and unblocks the parity test. Those are edge-honesty gains, not sprawl.

**D5. Strategy builder: keep drafting?**
- Architect and trader: all 22 drafts fail. That is free parameters, not edge, and it raises the trial count.
- Developer: the code works.
- **Decision:** stop the weekly LLM drafting job. Keep the builder for hand-written specs.
  - **Reason:** drafting adds multiple-testing load and LLM cost with zero passes.

**D6. `analyst_verdict`: fix or park?**
- AI pass: fix it with hysteresis and canonical views.
- Trader: it can't be backtested and closed 0 of 2. Keep it paper-only until its forward record clears n≥100, t≥2.
- **Decision:** park autopilot entries now. Rebuild on `ai_views` with hysteresis in P1, then let the forward record decide.
  - **Reason:** edge breaks the tie.

**D7. Cost filter: 3× (engine) vs 1.5× (fence)?**
- Developer: two constants for one rule.
- Trader: at a 5k cap neither saves the economics; what matters is that the minimum notional and the cost are computed at real size.
- **Decision:** one function in `lab/assumptions.py`, and one constant (2×) unless the re-run shows otherwise.
  - **Reason:** consistency between paths is what makes the paper record comparable.

**D8. Live readiness vs edge work.** Nothing ships to live until the architect's gates (P3) are met. The P3 work is sequenced after P1 because there is no strategy worth taking live yet.

---

## 6. Phased roadmap

Effort is S (≤1 day), M (2-4 days) or L (≥1 week). Each item lists its goal, the files it touches, the effort, a success metric and its dependencies.

### P0: stop the bleeding (make the numbers trustworthy)

| # | Goal | Files | Effort | Success metric | Dependencies |
|---|---|---|---|---|---|
| P0-1 | Picks autopilot enters grade A only; take `edge` from `adjusted`; rank by adjusted excess | `autopilot/picks.py:344-382`, `forecast/picks.py:116` | S | 0 new `pullback`/grade C entries; the pick doc's `edge` equals `adjusted.edge` | none |
| P0-2 | Park `analyst_verdict` autopilot entries and the 6 KILL engine strategies (scorecard) for autopilot | strategy registry / prefs, `autopilot/fence.py` | S | `autopilot_log` shows only allowed strategies | none |
| P0-3 | One exit engine: move `levels`/`exit_at_level` from `backtest.py:68-146` into `run()`; delete the monkeypatch | `engine/runner.py`, `engine/backtest.py` | M | intraday paper positions stop out intrabar; `backtest.py` shrinks by about 70 lines | none |
| P0-4 | Paper fills at the next open (intraday) and LONGTERM re-confirms the price against the signal at entry | `routers/trading.py:425`, `suggestions/service.py:49`, `autopilot/fence.py` | S | entries within X% of the signal's reference price; CANBK-type entries below the stop are refused | P0-3 |
| P0-5 | Golden-trade parity test: one fixture through `run_backtest` and through paper, asserting the exact net in rupees | `backend/tests/` | S | the test fails on any fill, exit or cost divergence | P0-3, P0-4 |
| P0-6 | Net of cost everywhere: `Portfolio.costs_paid`, `net_pnl` on `paper_trades`; kill switch, autopilot trip and analytics read net | `engine/portfolio.py`, `engine/persistence.py:147,160`, `routers/trading.py:452`, `autopilot/service.py:123`, `analytics.py` | S | kill-switch test with charges trips at the net limit | none |
| P0-7 | Silent-stop alerts: engine missing or no bars, Lab-off reported as its own line, news triage rate vs 7-day mean | `system/data_quality.py:134-140`, `engine/autorun.py:508` | S | an alert fires on a simulated stall | none |
| P0-8 | AI fail-safe: never cache a failed analyst score or report; required-field `_NewsScores`; `_rescored` returns None | `ai/analyst.py`, `suggestions/thesis.py` | S | unit test: an outage writes no `analyst:` or `sentiment:` key | none |
| P0-9 | Stale brief: `as_of` in `backdrop()` and the fact; a maximum age; a TTL on `market:brief` | `datalayer/market.py`, `ai/facts/market.py` | S | the brief never shows as current past 12 h in session | none |
| P0-10 | Re-run the 4 STALE intraday strategies plus `gap_and_go` (with `prev_closes`) under the honest backtester; mark the old rows invalid | `risk/gate_backtest.py:109-118`, `strategy_backtests` | S | every strategy on the scorecard has an honest row less than 30 days old | P0-3, P0-4 |

### P1: edge

| # | Goal | Files | Effort | Success metric | Dependencies |
|---|---|---|---|---|---|
| P1-1 | Validation gate: t≥2 on net expectancy, n≥100, positive in ≥2 regimes, walk-forward OOS, deflated by trial count | `risk/backtest_gate.py`, reusing `factor/validate.py::deflated_sharpe` | M | gate decisions log the t, the regimes and the trial count | P0-10 |
| P1-2 | Costs at real size: broker-specific brokerage calibrated against a contract note; Picks study netted at the account's cap; a minimum viable notional | `engine/execution/costs.py`, `forecast/study.py`, `lab/assumptions.py` | M | modelled vs contract-note charges within 2% on 5 real trades; Picks grades recomputed at 5k | Q2 |
| P1-3 | Point-in-time universe including delisted names | `factor/nifty200.csv` → dated membership, `daily_bars` | L | studies re-run; the change in adjusted excess is reported | none |
| P1-4 | Metrics from a daily MTM equity series that includes zero days | `engine/metrics.py` | S | Sharpe and drawdown computed the same way in backtest and scorecard | P0-6 |
| P1-5 | Entry hygiene: a downward-drift guard and a per-symbol cooldown after a stop | `engine/autorun.py:424-434`, `autopilot/fence.py` | S | no re-entry within N sessions of a stop | none |
| P1-6 | Risk: daily limit 1% while unproven, a weekly limit, a sector cap | `autopilot/fence.py`, prefs | S | the fence refuses on a sector or weekly breach | none |
| P1-7 | Picks evidence an analyst needs: MAE/MFE, holding-period decay, regime table, basket correlation, ADV and capacity | `forecast/study.py`, `forward/scorecard.py` | M | each column is present on the Picks study page | P1-3 |
| P1-8 | Universe and liquidity: one universe (Nifty 200) for scan and runs; an ADV floor; a price-band/T2T flag | `instruments/indian_stocks.py`, `fence.py:52-55` | S | 0 "outside Nifty 200" refusals | none |
| P1-9 | AI views: deterministic symbol and market views with hysteresis; verdict and sentiment derive from them; rebuild `analyst_verdict` on them | `ai/facts`, `datalayer/analysis.py`, `ai/analyst_verdict.py`, `ai/sentiment.py` | M | one `sentiment:` producer; no label flips inside the 0.12-0.18 band | P2-6 |
| P1-10 | Decision trace: `signal_log` for every rejected intent; per-fill cost breakdown plus `slippage_inr` | `engine/runner.py` (`size_intents`), `costs.py` | S | the UI answers "why didn't X trade" | none |
| P1-11 | Plan exits need a price or loss condition, and pass the fence | `plan/validate.py`, `engine/runner.py:387-410` | S | no plan exit without a numeric condition | none |

### P2: simplification

| # | Goal | Files | Effort | Success metric | Dependencies |
|---|---|---|---|---|---|
| P2-1 | Delete the dead research code and `lightgbm` | `forecast/research/*_tool.py`, `ml/`, `rl/`, `factor/survivorship.py`, `requirements.txt:35`, the `paper_limit_orders` index | S | about 1,470 fewer lines; smaller image; tests green | none |
| P2-2 | One `round_trip_cost`, one cost-filter constant | the 8 call sites in 3.2 | S | grep finds one friction formula | D7 |
| P2-3 | One `book_fill` (3 fill builders become 1); one P&L round-trip builder | `simulated.py`, `suggestions/service.py`, `broker.py`, `analytics.py`, `journal/roundtrips.py` | M | the parity test still passes | P0-5 |
| P2-4 | One ATR / RSI / EMA (fixes the `atr_14` label) | `strategies/indicators.py` as the owner; `blocks/state.py`, `forecast/picks.py`, `ai/facts/market.py` | S | one definition; tests pin the values | none |
| P2-5 | `candles_5m` store; backtests read it | `data/feeds/tick_bars.py`, `engine/backtest.py`, `risk/gate_backtest.py` | M | a gate re-run makes 0 Upstox calls; results are byte-identical on re-run | P0-5 |
| P2-6 | `llm.complete()` with `LLMError` and the `llm_calls` log; `get_completion` wraps it | `llm.py` | S | every call writes a row; budgets measurable per feature | none |
| P2-7 | Migrate callers to `complete(schema=…)`. Peers and hypotheses move to code, prune runs before triage, FAILED news is retried; chat moves to `get_view`/facts; grounding is applied to the review, index and learning outputs | the files of call sites 1, 2, 9, 14, 16, 17, 21, 22 | M | 0 in-band string checks left; FAILED count falls | P2-6 |
| P2-8 | Stop the weekly builder LLM drafting job | `builder/draft.py` scheduler entry | S | 0 new `built_strategies` per week | D5 |
| P2-9 | Per-bar writes become on-fill writes (`snapshot_positions`, `is_tripped` cached per run) | `engine/runner.py:561,671` | S | no per-bar Mongo writes | P0-3 |
| P2-10 | Replace the 3 daily LLM caps with per-feature caps derived from `llm_calls` | `configs/settings.py` | S | caps within 2-3× of real use | P2-6 |

### P3: live readiness (paper to small live capital)

No real money moves until every row below is met. G6 must also be re-earned on the unified engine: a strategy passes P1-1 **and** holds ≥30 trades and ≥20 days of paper record with paper within 1σ of its backtest expectancy.

| # | Gate | Files | Effort | Success metric | Dependencies |
|---|---|---|---|---|---|
| P3-1 | Idempotent orders: SUBMITTING row before send; `order.id` as the broker `tag` on Kite/Upstox/Angel One; cancel on age | `engine/execution/broker.py:45-57`, `brokers/*` | M | a crash-injection test shows no double send | none |
| P3-2 | Reconciliation as a gate: no entry if the last recon is not `ok`, or if the broker position disagrees with the ledger | `engine/broker_recon.py`, `autopilot/fence.py` | M | the fence refuses on mismatch | none |
| P3-3 | Kill switch flattens and halts: cancel working orders, square off, a manual stop-all, a trip on stale feed or marks | `risk/kill_switch.py`, `autopilot/service.py` | M | a dry run in paper flattens the book | P0-6 |
| P3-4 | Broker-side stop on live approvals (10-08 audit item 2) | `suggestions/service.py`, broker adapters | M | every live entry has an SL-M at the broker | P3-1 |
| P3-5 | Feed integrity: last-tick age, stop the run when stale, backfill on start, live quotes from the broker rather than Yahoo | `data/feeds/tick_bars.py`, `engine/runner.py`, `datalayer/marks.py` | M | a simulated socket drop halts entries within 1 bar | none |
| P3-6 | Deploy safety: refuse in-hours deploys while positions are open; an external `/health` probe; persistent logs | shared `ci-workflows` deploy workflow, compose logging | S | an in-hours deploy is blocked; probe alert tested | none |
| P3-7 | Exercise the live path once with the minimum quantity on one gated strategy, then reconcile | | S | one `live_orders` row reconciled end to end | P3-1 to P3-6 |
| P3-8 | Security: `rediss://`, after confirming the provider supports it | settings | S | TLS connection verified | none |

---

## 7. Do-not-build list

- No new strategies (intraday or AI-drafted) until P0-3 to P1-1 land. They add free parameters, not edge.
- No RL or ML trading paths. Both harnesses failed their bars; delete them (P2-1) and keep the findings in the ROADMAP.
- No new AI features or call sites. Every new opinion has to derive from `ai_views`.
- No second conviction formula or sizing path. Consolidate instead.
- No F&O work on these paths.
- No options or intraday UI polish (the redesign has shipped).
- No new services or queues for the AI layer. Extend `llm.py`.
- No user-facing Picks, Picks on Telegram, or paid suggestions (the 2026-10-18 decision and `PRODUCT.md`).
- No public beta (Phase 12) while `/suggestions` serves ideas to any signed-in user (W1, Q4).
- No live capital until P3 is fully met.
- No more news sources: GDELT has returned 429 all evening. Fix the existing pipeline's stall and retries first.

---

## 8. Owner questions (answers change the plan's direction)

- **Q1.** Was Lab switched off on purpose after 10-16? If yes, P0-7 reports it as a line rather than an alert, and intraday stays parked per D1.
- **Q2.** The account size stays at 25k with a 5k cap? At that size CNC needs more than 1.2% expected gross just to break even. The options are fewer and larger positions, more capital, or an index/ETF sleeve. This decides the P1-2 thresholds.
- **Q3.** Set the effective AI weight in sizing to 0 until it is validated (D3)? This changes `composite.py`'s blend, which is an invariant.
- **Q4.** Before any second user: should `/suggestions` and the Telegram idea digest become admin-only, or stay a free own-account tool under `PRODUCT.md`? (W1)

## 9. Unknowns

- Why news triage stalled on 2026-10-20 to 10-23; the logs were lost at recreate.
- Whether the live intraday feed was Kite ticks or delayed yfinance polling on any given day.
- Whether broker daily candles are split-adjusted.
- The real Yahoo quote delay.
- Whether the Redis endpoint enforces TLS.
- Whether an external uptime monitor exists.
- The dollar cost per LLM call.
- The factor book's out-of-sample verdict.
- How `plan_scorecards` arm "b" is computed.
- Whether the FAILED or empty-impact news items hid material news.

---

## Appendix: regime split (trader persona)

Trend is defined by Nifty against its 200-day mean; volatility by the 20-day realised vol against its median. Each cell is n / expectancy (INR) / PF.

| Strategy | trend_up | trend_down | vol_hi | vol_lo |
|---|---|---|---|---|
| trend_day_pullback | 826 / -4.9 / .84 | 1419 / -4.6 / .84 | 745 / -4.5 / .86 | 1500 / -4.8 / .83 |
| gap_fill_fade | 271 / -4.2 / .86 | 796 / -5.0 / .86 | 363 / -4.6 / .88 | 704 / -4.9 / .85 |
| relative_strength_sector | 156 / -9.7 / .77 | 183 / -12.9 / .88 | 90 / -12.4 / .90 | 249 / -11.0 / .82 |
| technical_breakout | 24 / -46 / .51 | 70 / -39 / .64 | 43 / +0.9 / 1.01 | 51 / -76 / .39 |
| macd_crossover | 58 / -30 / .60 | 32 / -43 / .42 | 27 / -41 / .45 | 63 / -32 / .57 |
| mean_reversion | 14 / -107 / .40 | 47 / -48 / .57 | 21 / -75 / .33 | 40 / -55 / .59 |
| built:orb-break-long | 362 / -8.2 / .70 | 495 / -3.8 / .88 | 216 / -5.4 / .87 | 641 / -5.8 / .78 |
| built:swing-gap-hold | 117 / -39 / .67 | 0 | 53 / -91 / .46 | 64 / +3.8 / 1.05 |

No strategy is positive in any regime cell with n≥100. The long-only intraday strategies lose more when the trend is up. Coverage is thin: the 1-year windows are mostly trend_down, and the 3-year swing windows are about 98% trend_up.
