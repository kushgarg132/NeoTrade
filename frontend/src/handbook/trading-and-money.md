# Trading & Money

Two accounts, one decision path, and the rails that sit between a signal and a real order
(Phase 19, `docs/superpowers/specs/2026-10-14-two-accounts-reset-design.md`).

## Two accounts

| Account | What it is | Ledger (`paper_*` collections, `user_id` field) | Who can place orders |
|---|---|---|---|
| **Mine** (role `mine`) | Your own broker account | `<user>:mine` for orders the app placed (`engine/persistence.py::mine_book`); your real holdings are `portfolio/service.py::mine_holdings` | Only you, for real money: a one-tap approval, a chat card or the order ticket, each confirmed twice. There is no paper venue here |
| **AI** (role `ai`) | A separate broker account the app runs | paper: `<user>` (the engine, the factor portfolio, the autopilot); live: `<user>:autopilot` | The engine and the autopilot, without a tap, inside the fence |

The AI account on paper is what used to be called Practice. Every trade keeps `strategy` = the strategy whose idea
it was and `via` = the path that placed it (e.g. `autopilot:engine`), so the paper gate and
learning credit the right strategy. The AI book as a whole is
`autopilot/service.py::ai_book_query`. Nothing routes an AI order to `mine`, and nothing
falls back from one account to another.

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
- **Sizing lives in `size_intents` + `RiskRules`** (`backend/risk/rules.py`), never
  in a strategy. Risk per trade scales with conviction: `BASE_RISK_PCT × final score`.
  An entry whose target cannot beat `COST_MULTIPLE` (3) × its round-trip charges and slippage
  is dropped; each run counts these in `progress.below_cost`, shown on Paper → engine as
  "too small to beat charges".

## Strategies

Registered in `backend/strategies/registry.py`; each class carries a `CARD`
(`backend/strategies/card.py`: style, regimes it suits, conditions, best/avoid, typical
hold), shown in Lab → Strategies with this account's record and what each still needs.

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

## Strategy builder

The AI drafts strategies from a fixed vocabulary of blocks (setups, filters, stops, targets:
`backend/strategies/blocks/vocab.py`); it never writes code, only a spec the blocks interpret.

Weekly (Friday, `backend/builder/draft.py::run`, details in Jobs & Ops): up to 3 drafts, each
validated (`backend/builder/validate.py::validate_spec`, duplicates dropped) and backtested over a year of
5-minute bars. A draft goes **active** only if all three checks pass:

1. The backtest gate: profit factor ≥ 1.3, ≥ 30 trades, drawdown ≤ 15%, ≥ 365 days.
2. The last 90 days alone are net-positive (the holdout).
3. Deflated Sharpe ≥ 0.95 over every draft ever tried, so a lucky draw among many does not pass.

Active strategies appear in Lab → Strategies as `built:<slug>` with a **Built** badge; failures sit
under "Tried and rejected" with the reason. They trade on paper first, then need both gates to real money
(above) like any strategy. Each takes at most one entry per symbol per day and exits by its stop, target or the
15:15 square-off. `backend/strategies/built.py::BlockStrategy` starts each symbol fresh every session, seeded
only with the previous close, so a backtest and a live feed see the same indicators (ATR and volume blocks
warm up each morning). At most 5 are active
(`draft.py::MAX_ACTIVE`); one the learning rules keep paused for 30 days is retired
(`draft.py::_retire_paused`).

**Swing drafts** (`"horizon": "swing"`, daily-bar blocks) are a second weekly prompt
(`backend/prompts/strategy_builder_swing.md`, up to 3 more drafts) and their own 5-active cap
(`draft.py::_make_room`). They test on 3 years of the stored daily bars after 300 days of warm-up
(`draft.py::_swing_history`; no broker session needed; fewer than 30 symbols with bars leaves them
`testing`), with delivery charges. Four checks: the same gate, the last **180** days net-positive,
deflated Sharpe over swing drafts only (`backend/builder/store.py::trial_sharpes`), and the
**benchmark**: the net return over the 3 years must beat an equal-weight buy-and-hold of the same
stocks, less one round trip of charges (`draft.py::_benchmark`; "benchmark: +x% < buy-and-hold +y%").

Swing blocks (`backend/strategies/blocks/vocab.py::SWING_SETUPS` / `SWING_FILTERS` / `SWING_EXITS`): setups `breakout_n`, `pullback_ma`,
`rsi2_dip`, `gap_hold`, `momentum_rank`, `volume_breakout`; filters `trend_ma`, `regime_is`, `sector_rs`,
`atr_pct`, `liquidity`. Swing is long only. Exits: a stop (`atr_multiple` or `swing_low`, the lowest low of
the last 5 bars), a target (`r_multiple`), a required `max_hold_days` and an optional `trail_atr`. A swing
trade is held up to `max_hold_days` days and exits by the first of stop, target, trail or the time limit.
The 5-active cap is per horizon (`routers/settings.py::_check_caps`); the 3-a-day and one-testing limits
are shared across both.

### Your own strategies

The chat can do the same: `backend/chat/actions.py::action_tools` offers `propose_strategy`, which validates the
spec and returns a card; Confirm runs `submit_strategy` itself, so every limit and the test are the form's.

Lab → Strategies → **Mine** → **New strategy** composes a spec from the same blocks. Pick the **Horizon**
(Intraday / Swing) first; Swing hides Short and asks for `Max hold (days)` and an optional
`Trailing stop (× ATR)`. Rows carry an Intraday / Swing chip. The chat's `propose_strategy` lists both
vocabularies and takes `"horizon": "swing"` in the spec. (The form reads
`GET /strategies/vocabulary`, which returns `{intraday, swing}`, `backend/routers/settings.py::strategy_vocabulary`; the live preview is
`describe_strategy`). `submit_strategy` validates it, stores it private to you (`owner_id`; the loader and
the library show your strategies only to you, never to other users) as `testing` and starts its backtest
(`backend/builder/draft.py::test_one`). Same three checks as the AI's drafts, so a pass is **active** for you
and a fail is **rejected** with the first reason. Limits, shown as-is when hit:

- "3 strategies a day: try again tomorrow." (IST day; a Re-test counts too)
- "A strategy of yours is still being tested." (one at a time)
- "You have 5 active swing strategies. Retire one first." (5 active at most per horizon; says "intraday" for those)

The test uses the admin's Upstox year of 5-minute bars (the only history source; none yet leaves it
`testing` as "waiting for market history" until the weekly run) but sizes trades with **your** account size,
max invested and per-trade cap. The Deflated Sharpe counts only **your** earlier tried drafts, not the AI's.
`retire_strategy` retires an active one for good; `retest_strategy` re-runs a rejected one as a new trial.

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
- **Guardrails** (Journal → Guardrails) — `backend/guardrails/`: limits you set on your own broker account
  (trades per day, cooldown after losses, daily loss, options trades and lots, unhedged
  option selling), checked every minute 9:15 AM–3:35 PM IST. Alerts only — nothing here can
  stop an order you place in the broker's app.
- **Auto square-off** — pref `auto_square_off` off / preview / live
  (`backend/guardrails/square_off.py`): on a daily-loss breach, MARKET exits for NSE MIS
  positions, at most once a day. The one path that sends real orders without a per-trade
  tap; never yet run against a live account.
- **AI game plan only tightens** — `backend/plan/`: may drop opening intents, shrink risk
  (0.25–1.0), cap positions or skip the day; never blocks an exit or touches conviction.

## Long-term ideas (Portfolio → Needs you)

Decided from the "Needs you" list on `/portfolio` (there is no Ideas tab since 2026-10-15; `/mine/ideas` redirects to `/portfolio`). Approving
there never trades the AI account: fills go to paper or, on a second tap, to `mine`.


- Made by the 4:00 PM IST scan (`backend/suggestions/scan.py::scan_universe`: ~400 days of
  history through the same runner, armed only on the final session) and by material news
  (`news_scan`, `source="news"`).
- Stored by `SuggestionStore.create` with the sized order and the `{rule, ai, final}` breakdown;
  `attach_theses` rescores once research has measured real sentiment.
- Approve / reject is one atomic `find_one_and_update` gated on PENDING — double approval
  is impossible. Approval is real money on `mine` (second tap), booked in `<user>:mine`.
  The second tap is checked by the server: `approve-live` without a token only returns a
  one-time `confirm_token` (`backend/risk/live_confirm.py::issue`, 60 s, bound to the user,
  the proposal and its terms); the call that presents it places the order
  (`routers/suggestions.py::approve_suggestion_live`). The same token guards chat, ticket and Telegram cards.
  On the web the second tap shows a 60 s countdown; if it runs out, or the server refuses the token
  (expired, used, order changed), the card goes back to its first tap with a short reason. Nothing is retried.
  There is no paper approval: the AI account paper-trades proposals itself.
- Expire after 3 days (`DEFAULT_TTL`). An equity SELL is proposed only against a held long.
- At most 5 long-term proposals stay pending, the best by final score: after each scan the rest
  expire as `outranked` (`scan.py::MAX_PENDING_LONGTERM`, `store.py::keep_best`), so theses are
  written only for those. Each must already beat 3× its round-trip charges (`size_intents`).
- **Ideas for the user's account come only from proven strategies**
  (`risk/paper_gate.py::for_mine`: a passing backtest and a passing paper record on the AI
  account). Portfolio → Overview, Today, the chat, portfolio picks and every proposal Telegram message read
  through it, and approve-live refuses an unproven one with a 409. Until a strategy is proven the
  AI paper-trades its ideas alone. A proposal the AI took stays PENDING with `ai_order` set, so
  both accounts can act on the same idea.
- Exits: the autopilot sells its own positions at the proposal's stop or target. On the user's
  own account `suggestions/exits.py::check_exits` only **alerts** (every 15 min in session, once
  per trade and reason) for app-placed longs in `<user>:mine`, and closes a trade as `sold` once
  its stock has left the user's holdings. A swing proposal also exits after `max_hold_days` trading days and at
  a trailing stop (highest close since entry − k × 14-day ATR, never lowered, kept as
  `trail_stop`), by `exits.py::exit_reasons`, which the autopilot's exits share; the backtest
  applies the same rules (`engine/backtest.py::run_backtest`), counting bars held rather than weekdays,
  fills any position whose bar opens through its stop at that open, and checks the entry bar itself
  (filled at its open) against the stop and target.

## The autopilot (AI account)

`backend/autopilot/` places orders on the `ai` account without a tap — the one documented
exception to the backtest gate and to "model output never places an order". Every entry
passes `autopilot/fence.py::check` against the shared trading limits (one set for paper and
live, edited on AI → Autopilot: `max_exposure`, `per_trade_cap`, `max_trades_per_day`,
`daily_loss_limit` — the same fields the AI account and Watch my broker read; 0 trades or loss is off),
its own daily-loss trip, the shared kill switch, Nifty 200 names, NSE equity, market hours; exits
are never blocked, not even with the autopilot off. Risk-off halves the per-trade cap and refuses news entries; a high-impact
event within 30 min refuses all entries; news entries stop at 3 a day. One switch, Off ·
Paper · Live (Live needs a typed confirmation). On paper it fills in the AI paper book
(`autopilot/service.py::book`), every trade marked `via="autopilot:<source>"` with `strategy`
the proposal's; the fence counts only `via` trades and refuses a symbol another strategy holds
there (one owner per position, as in the engine), and the engine's long-term exits skip them.
Live fills go to their own `<user>:autopilot` book. `autopilot/service.py::check_exits` runs
for anyone holding autopilot trades, on or off, and squares off intraday positions from 15:15. Live, it takes a stock proposal (morning pass
or news) only when the proposal's strategy passed both gates, its latest backtest and its
paper record (`risk/paper_gate.py::proven_strategies`). Paper takes them all, to build the
record that decides what reaches the user. While the autopilot is on (paper or live), the 4 PM scan and the long-term pass run
whatever their own switches say (`prefs.py::scan_enabled_users`, `engine/autorun.py::tick`): it
trades the scan's proposals and acts in that pass, and used to sit idle with either off. Every order and refusal goes to
`autopilot_log` and Telegram with a Stop button. It also trades Picks (`source="picks"`, quietly;
see Picks below).

## The AI paper book: runs, books, learning

Under AI, one job per tab: **Overview** (the autopilot and its capital, what the engine is
doing now, today net of charges, what it traded), **Activity** (every autopilot order and
refusal), **Book** (the paper money over Today / Month / All time, net of charges, from closed
trades), **Strategies** (which strategy is good enough, the track record, learning),
**Settings** (the autopilot, the engine switches, the limits, each strategy's paper / live switch).
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
  any other variant. Shown under Lab → Strategies → What the engine learned.

## Portfolio (Portfolio → Holdings)

Holdings from every connected broker merged by ISIN (`backend/portfolio/scorecard.py`),
health per stock (`portfolio/health.py`), rule verdicts SELL / HOLD / ADD (funds REVIEW /
KEEP) scored through `composite.py`, an AI write-up that explains but never decides, and an
admin-only AI action plan. Verdicts are admin-only until `portfolio_verdicts` is `all`
(needs SEBI RA registration). The review, its verdicts and its AI text cover the user's own
(`mine`) account only; the AI account's holdings show without verdicts. Re-reviewed every
trading day after the close (`portfolio/service.py::daily_reviews`), with a Telegram alert
when a verdict gets worse. A broker that is logged out keeps its last holdings
(`fetch_holdings` carries them over), priced from market quotes and marked "holdings as of".
`portfolio/service.py::mine_holdings` is what the rest of the app means by "held": news
alerts and the long-term scan's SELL ideas read it, never paper positions.

## Mine redesign (Portfolio → Overview · Holdings · Tax, and Journal)

Since 2026-10-19 the old Mine section is Portfolio (Overview · Holdings · Tax · News · Watchlist · Import) plus a
separate Journal tab (Trades · Habits · Guardrails) and one stock page at `/stock/:symbol`; Today is the glance,
Portfolio is the depth. Old paths redirect in one hop (`frontend/src/utils/routes.js::MOVED`: `/mine` → `/portfolio`,
`/mine/journal` and `/mine/trades` → `/journal`, `/mine/habits` → `/journal?tab=habits`). The Plan and Review sub-tabs, the
"Analyse now" button and the Ideas page are gone; the daily 16:00 review still writes verdicts and the
per-holding AI note, and `POST /portfolio/refresh` stays for the daily pass and the chat. Nothing here
adds scoring: verdicts stay admin-gated and the one conviction formula is untouched.

Backend, `backend/mine/` behind `backend/routers/mine.py` (`/mine/*`, every record carries `user_id`):

- **Lots** (`backend/mine/lots.py::open_lots`, `::realised`, `::reconcile`): FIFO tax lots from the
  journal's trades (`::mine_trades`); the shortfall against the broker quantity shows as "unknown", and
  sells with no journal buy come back from `::unmatched`. `::split_ratio` treats a whole-number excess as a
  split or bonus only when the broker's average price is the journal's divided by that ratio (within 2%).
- **History** (`backend/mine/history.py::backfill`, `::write_all`, `::series`): `mine_daily` holds the
  account's value, net invested and the NIFTY-equivalent value per day. Backfill replays journal trades
  over stored closes (sells clipped to what the journal holds, split-scaled to match the adjusted bars);
  the 16:00 pass (`backend/scheduler.py`, via `::write_all`) recomputes every user's whole curve and
  upserts what changed, so a later import fixes the past.
  `::xirr` is stdlib Newton with a bisection fallback; `::returns` gives the account's and NIFTY's XIRR
  on the same cash flows.
- **Needs you** (`backend/mine/actions.py::build`): one ranked list of verdict changes, target/stop
  levels, proven ideas, rebalance buys and results dates. `::dismiss` and `::snooze` (7 days) keep state
  per user; `::level_alerts` feeds Telegram from its own step in the auto-run tick
  (`backend/engine/autorun.py::_level_pass`), not the long-term pass.
- **Thesis** (`backend/mine/thesis.py::ThesisStore`, `::ThesisIn`): why, target, stop and review-by per
  holding, in `holding_theses`.
- **Events** (`backend/mine/events.py::refresh`, `::loop`): results and ex-dividend dates of held symbols
  into `corporate_events` from yfinance, a 6 hour loop in the ingest worker
  (`backend/datalayer/worker.py`); `::dividends_received` estimates dividends from quantity held on the ex-date.
- **Tax** (`backend/mine/tax.py::report`): Indian FY realised gains split short/long term, the
  Rs 1.25 lakh exemption (`::est_tax`), unrealised by lot, lots turning long-term soon and the 31 March
  harvest lists (a loss harvest's saving is the drop in this FY's estimated tax; zero is not listed).
  FY 2025-26 onward only (`/mine/tax` refuses earlier years, which had other rates). An estimate, not
  tax advice; rates live only here.
- **Stock** (`backend/mine/stock.py::detail`): position, lots, thesis, verdict history, events, news and
  closes for one symbol; a sold holding still opens.

Frontend: `frontend/src/pages/MineOverview.jsx::MineOverview` (headline with XIRR vs NIFTY, value curve
`frontend/src/components/mine/ValueCurve.jsx`, Needs you `frontend/src/components/mine/NeedsYou.jsx`,
drivers, mix), `frontend/src/pages/MineHoldings.jsx::MineHoldings` (one line per holding, sort and filter
chips, "Plan new money" opens `frontend/src/components/portfolio/Rebalance.jsx`),
`frontend/src/pages/MineStock.jsx::MineStock` (lots, chart with trade markers, thesis editor
`frontend/src/components/mine/ThesisEditor.jsx`), `frontend/src/pages/MineTax.jsx::MineTax` and
`frontend/src/pages/Journal.jsx` (Trades and Habits as inner tabs). Where an action opens is decided in
`frontend/src/utils/mine.js::actionTarget`.

## Picks (Picks, admin-only)

Which stocks fired a setup at the last close, and what that setup has done before — every
number a measured base rate, never a model's opinion. Admin-only everywhere until the owner's
SEBI Research Analyst registration exists: the router takes `require_admin`
(`backend/routers/picks.py::router`), the tab is dropped for non-admins
(`frontend/src/components/layout/SectionTabs.jsx::SectionTabs`, `admin: true`), and nothing
reaches Telegram, digests or chat.

- **Setups** (`backend/forecast/setups.py::SETUPS`): momentum leader and low-volatility leader
  (top decile of `factor/model.py::scores`, re-ranked on the first trading day of each month),
  momentum over volatility (`setups.py::momentum_vol`: 12-1 month return over 60-day volatility,
  top decile on each month's first trading day, held 60 days), 52-week-high close on ≥1.5x
  20-day average volume, and close above the 200-day SMA with RSI(14) < 35. Each has a fixed
  horizon. A signal on day t reads rows up to t only. The study reads every stored bar (from 2009,
  `picks.py::HISTORY_START`).
- **Events** (`backend/forecast/study.py::events`): entry t+1 open, exit close of t+1+H; net of
  10 bps slippage per side (`lab/assumptions.py::round_trip_return`) and CNC charges from `engine/execution/costs.py::calculate_indian_costs` on a ₹1L position; NIFTY
  over the same window. `study.py::kept` drops signals inside an open event's window.
- **Walk-forward** (`study.py::walk_forward`): each year's P(up) is predicted only from events
  that matured before it began, then scored (realised hit rate, Brier). Out-of-sample excess
  over NIFTY ≤ 0 marks the setup "no edge"; its picks still show, badged.
- **Daily job** (`backend/forecast/picks.py::run`, in the 16:00 pass): stores today's picks in
  `picks` before the outcome exists (top 10 by median excess × P(beat NIFTY), setups with
  n ≥ 100 only), scores matured ones, and writes the study to `picks_study`. The forward record
  (`picks.py::forward`) stays "unproven" until 100 picks are scored.
- **The AI account trades them** (`backend/autopilot/picks.py`, owner decision 2026-10-17), as the
  forward track record, for admins only: `picks.py::enter` buys the last session's picks at the
  first long-term pass after the open (09:20), best first, each sized to the per-trade cap in force,
  through `autopilot/service.py::submit` (fence, kill switch, max invested, trades a day), CNC, long
  only; `picks.py::exit_due` sells from 15:15 on the pick's `due_date` (the close of its horizon),
  exits never blocked. Each trade carries `strategy="picks:<setup>"`, `via="autopilot:picks"` and
  the pick's id in `context`. Nothing goes to Telegram. Paper only until the forward record passes
  `forecast/picks.py::live_refusal` (≥100 scored, calibration within 5 points, positive mean excess
  over NIFTY) and the owner turns on both `picks_live` and the autopilot's Live mode; AI → Autopilot
  shows that row disabled. Today's **You vs Picks** (`portfolio/digest.py::scoreboard`, admin-only)
  sets your account against these trades, net of charges.
- **Caveat**: the universe is today's stock list (survivorship); the payload says so.

## Reproducing a run

Every simulator leaves a `lab_runs` record (`backend/lab/runs.py::LabRunStore`). To check one still
reproduces, run `python -m backend.lab rerun <id>` (`backend/lab/__main__.py::rerun`) inside the
backend container. For a `factor` or `study` run it rebuilds the inputs from the stored window and
config (bars after the window are ignored), re-runs the same code (`backend/factor/report.py::run`,
`backend/forecast/study.py::run`) and compares the data fingerprint and every metric to 1e-6.
Exit 0 means identical, 1 means something differs (the printed `deltas` say what; a changed
fingerprint means the underlying prices moved), 2 means the kind (`engine`, `ml`, `bandit`) is not
re-runnable here.
