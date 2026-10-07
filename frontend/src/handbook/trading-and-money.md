# Trading & Money

Three kinds of money, one decision path, and the rails that sit between a signal and
a real order.

## Three kinds of money

| Account | What it is | Where in the app | Who can place orders |
|---|---|---|---|
| **Mine** (role `mine`) | Your own broker account | Mine → Holdings / Trades / Habits | Only you: chat cards and the order ticket, each confirmed (twice for live) |
| **AI** (role `ai`) | A separate broker account the autopilot trades | AI → Overview / Activity / Autopilot | The autopilot, without a tap, inside its fence |
| **Practice** (paper) | The strategy engine's simulated book | More → Practice | The engine on paper; approvals fill on paper or, on a second tap, on your own account |

Nothing routes an AI order to `mine`, and nothing falls back from one account to another.

## The decision path

One path turns market data into a trade. The LLM is not in it.

```
bar / tick → Strategy.on_bar → Intent → score_intent → size_intents → Proposal
          → INTRADAY: execution.submit → fill → portfolio + ledger
          → LONGTERM: SuggestionSink → suggestions → you approve → fill
```

| Stage | Where | Produces |
|---|---|---|
| Strategy | `backend/engine/protocols.py::Strategy`, `backend/strategies/base.py` | `Intent` |
| Scoring | `backend/scoring/composite.py::score_intent` | `CompositeScore` or `None` |
| Sizing | `backend/engine/runner.py::size_intents` | `Proposal` |
| Routing | `backend/engine/runner.py::run`, `backend/suggestions/sink.py` | order or suggestion |
| Fills | `backend/engine/execution/` (`simulated`, `broker`, `routing`, `autopilot`) | `Fill` |
| Book | `backend/engine/portfolio.py`, `backend/engine/persistence.py::LedgerStore` | positions, P&L, ledger |

`Intent` (`backend/core/models.py::Intent`) is deliberately thin: symbol, side, strength
0–1, non-empty `reason_codes`, stop and target hints. No price, size or time — those are
added downstream, which is what makes the cap below enforceable.

## The invariants

These make conviction legible. Enforced in code and tests, not by discipline.

- **AI is capped at 30% of conviction.** `AI_CAP = 0.30` (`composite.py:15`);
  `CompositeScore.__post_init__` clamps `ai_weight` on a frozen dataclass, so 0.99 still
  becomes 0.30. Tested in `backend/tests/test_composite_score.py`.
- **AI cannot rescue a trade the rules did not support.** `RULE_FLOOR = 0.45`
  (`composite.py:16`); `score_intent` returns `None` below it and the runner drops the intent.
- **Exactly one conviction formula.** Any new idea source emits `Intent` and goes through
  `composite.py`.
- **Every intent carries reasons.** `Intent.__post_init__` rejects empty `reason_codes`.
- **Every per-account record carries `user_id`.**
- **Sizing lives in `size_intents` + `RiskRules`** (`backend/components/risk/risk.py`), never
  in a strategy. Risk per trade scales with conviction: `BASE_RISK_PCT × final score`.
  An entry whose target cannot beat `COST_MULTIPLE` (3) × its round-trip charges and slippage
  is dropped; each run counts these in `progress.below_cost`, shown on Paper → engine as
  "too small to beat charges".

## Strategies

Registered in `backend/strategies/registry.py`; each class carries a `CARD`
(`backend/strategies/card.py`: style, regimes it suits, conditions, best/avoid, typical
hold), shown in Practice → Strategies with this account's record and what each still needs.

- **Intraday:** `orb_breakout`, `vwap_reversion`, `volume_surge`, `rsi_momentum_scalp`, and the
  news-aware set `gap_and_go`, `gap_fill_fade` (per-day catalyst map,
  `backend/datalayer/catalysts.py`), `trend_day_pullback`, `relative_strength_sector`
  (vs Nifty 200 sector peers in the same run); `orb_options` buys the ATM call/put on an
  ORB breakout in ten liquid F&O names, paper only for priced contracts.
- **Long-term:** quality momentum, analyst verdict, technical breakout, MACD crossover,
  mean reversion (`backend/strategies/longterm/`), the cash-secured put, and the
  **factor portfolio** (`backend/factor/`: Nifty 200 momentum + low-vol, monthly rebalance,
  risk-off below the 200-DMA) on its own paper book.

Under the honest backtester (net of charges, 10 bps slippage) every intraday strategy loses
before charges too (PF 0.63–0.80). Intraday stays experimental and off by default. The
factor portfolio backtests best (2012–2026: ~19% CAGR, Sharpe 1.6, max DD −16%), but on
today's Nifty 200 list: measured against survivorship-free yardsticks that flatters it by
~4–8% a year (`backend/factor/survivorship.py`, ROADMAP 17.3.1), leaving no clear edge over
the index. Its forward paper record is the evidence that counts.

**Who follows a live order.** Every real order is a `live_orders` row. One the engine sent has
no broker role and is polled only by its run (`BrokerExecutionClient.poll_once`); one sent by
approve-live, the chat or the autopilot carries its role (`mine` / `ai`) and is followed only
by the reconciler (`engine/reconcile.py`), which books late fills to that row's ledger. Every
status change is a compare-and-set (`LiveOrderStore.claim`), so a fill seen by two of them —
a run and the user's other run, or `execute_live_order` and the reconciler — is booked once.

## Gates to real money

A strategy switched live routes real orders only if all of these hold. Each is code, not policy.

1. **Backtest gate** — `backend/risk/backtest_gate.py`: a stored, dated backtest meeting the
   criteria (recorded by `backend/risk/gate_backtest.py`, admin `POST /trading/backtests/{name}`).
2. **Paper gate** — `backend/risk/paper_gate.py`: in that user's account, ≥ 20 trading days,
   ≥ 30 trades, net profit after charges, profit factor ≥ 1.3, drawdown within 5% of account size.
3. **Live toggle + ACTIVE broker session** for the `ai` role (engine) — checked in `launch_run`.
4. **Option orders** only through a broker with `supports_options` (Kite, Upstox).

Every run still runs every strategy on paper; the gates decide only where orders go.

## Rails that hold every day

- **Daily loss kill-switch** — `backend/risk/kill_switch.py`: once realised + unrealised loss
  crosses the user's limit, live trading stops for the session and does not re-arm itself.
- **Capital caps** — per-trade and per-day, read from stored prefs, never the request body.
- **Guardrails** (Mine) — `backend/guardrails/`: limits you set on your own broker account
  (trades per day, cooldown after losses, daily loss, options trades and lots, unhedged
  option selling), checked every minute 9:15 AM–3:35 PM IST. Alerts only — nothing here can
  stop an order you place in the broker's app.
- **Auto square-off** — pref `auto_square_off` off / preview / live
  (`backend/guardrails/square_off.py`): on a daily-loss breach, MARKET exits for NSE MIS
  positions, at most once a day. The one path that sends real orders without a per-trade
  tap; never yet run against a live account.
- **AI game plan only tightens** — `backend/plan/`: may drop opening intents, shrink risk
  (0.25–1.0), cap positions or skip the day; never blocks an exit or touches conviction.

## Long-term proposals (AI → Decisions)

Decided at `/ai/decisions` (moved from Practice 2026-10-06; old paths redirect). Approving
there never trades the AI account: fills go to paper or, on a second tap, to `mine`.


- Made by the 4:00 PM IST scan (`backend/suggestions/scan.py::scan_universe`: ~400 days of
  history through the same runner, armed only on the final session) and by material news
  (`news_scan`, `source="news"`).
- Stored by `SuggestionStore.create` with the sized order and the `{rule, ai, final}` breakdown;
  `attach_theses` rescores once research has measured real sentiment.
- Approve / reject is one atomic `find_one_and_update` gated on PENDING — double approval
  is impossible. Approval fills against a fresh price, on paper or (second tap) live on `mine`.
- Expire after 3 days (`DEFAULT_TTL`). An equity SELL is proposed only against a held long.
- At most 5 long-term proposals stay pending, the best by final score: after each scan the rest
  expire as `outranked` (`scan.py::MAX_PENDING_LONGTERM`, `store.py::keep_best`), so theses are
  written only for those. Each must already beat 3× its round-trip charges (`size_intents`).
- Approved long-term paper positions exit at their stop or target (`suggestions/exits.py`,
  every 15 min in session).

## The autopilot (AI account)

`backend/autopilot/` places orders on the `ai` account without a tap — the one documented
exception to the backtest gate and to "model output never places an order". Every entry
passes `autopilot/fence.py::check` against the shared trading limits (one set for paper and
live, edited on AI → Autopilot: `max_exposure`, `per_trade_cap`, `max_trades_per_day`,
`daily_loss_limit` — the same fields Practice and Watch my broker read; 0 trades or loss is off),
its own daily-loss trip, the shared kill switch, Nifty 200 names, NSE equity, market hours; exits
are never blocked. Risk-off halves the per-trade cap and refuses news entries; a high-impact
event within 30 min refuses all entries; news entries stop at 3 a day. One switch, Off ·
Paper · Live (Live needs a typed confirmation). On paper it fills in the user's Practice
book (`autopilot/service.py::book`), every trade tagged `strategy="autopilot:<source>"`; the
fence counts only tagged trades and refuses a symbol another strategy holds there (one owner
per position, as in the engine), and the engine's long-term exits skip tagged trades. Live
fills go to their own `<user>:autopilot` book. Live, it takes a stock proposal (morning pass
or news) only when the proposal's strategy passed both gates, its latest backtest and its
paper record (`engine/autorun.py::_proven_strategies`); the rest wait for the user. Paper
takes them all, to build the record. While the autopilot is on (paper or live), the 4 PM scan and the long-term pass run
whatever their own switches say (`prefs.py::scan_enabled_users`, `engine/autorun.py::tick`): it
trades the scan's proposals and acts in that pass, and used to sit idle with either off. Every order and refusal goes to
`autopilot_log` and Telegram with a Stop button.

## Practice: runs, books, learning

Three tabs, one job each: **Engine** (what it is doing now, today net of charges),
**Book** (the practice money over Today / Month / All time, net of charges, from closed
trades), **Strategies** (which strategy is good enough, the track record, learning).
`compute_pnl` reports `costs` and `net` per period and `all_time`.


- **Auto run** — `backend/engine/autorun.py`: keeps one INTRADAY paper run alive 9:15 AM–3:30 PM
  IST for users with `auto_paper_intraday`; `autorun:<user>` (150 s TTL) decides which worker
  owns it. A run you stop stays stopped that day; at most 5 starts a day.
- **Two books** — every fill carries `venue` (`paper` / `live`); "paper" reads as "not live",
  so old rows never leak into the live book.
- **Scorecard** — `backend/analytics.py::compute_scorecard`: net of charges, per day and per
  strategy, profit factor, win rate, max drawdown, NIFTY 50 over the same days.
- **Learning loop** — `backend/learning/`: nightly, pause a strategy losing over ≥ 30 trades,
  raise its strength floor, skip a losing regime (entries only). Monthly re-tune with a Deflated
  Sharpe guard: daily-bar strategies on three years of yfinance closes, 5-minute ones on a year
  from the admin's Upstox (or Kite) session (`backend/risk/gate_backtest.py::intraday_history`),
  skipped when neither is logged in. The LLM may only *suggest* thresholds, which are tested like
  any other variant. Shown under Practice → Strategies → What the engine learned.

## Portfolio (Mine → Holdings)

Holdings from every connected broker merged by ISIN (`backend/portfolio/scorecard.py`),
health per stock (`portfolio/health.py`), rule verdicts SELL / HOLD / ADD (funds REVIEW /
KEEP) scored through `composite.py`, an AI write-up that explains but never decides, and an
admin-only AI action plan. Verdicts are admin-only until `portfolio_verdicts` is `all`
(needs SEBI RA registration). Re-reviewed Friday after the close, with a Telegram alert when
a verdict gets worse.
