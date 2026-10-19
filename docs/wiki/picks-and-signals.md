---
page: picks-and-signals
covers: [backend/lab/**, backend/ml/**, backend/forward/**, backend/forecast/**, backend/factor/**, backend/scoring/**, backend/suggestions/**, backend/learning/**, backend/builder/**, backend/data/fundamentals/**, backend/routers/picks.py, backend/routers/suggestions.py]
verified_at: 98573be
---
# Picks and signals: Picks, factor portfolio, scoring, long-term suggestions, learning, builder

Everything that turns market data into a trade idea and judges ideas afterwards. **Picks**
(`backend/forecast/`) stores measured-base-rate setups daily, admin-only. The **factor
portfolio** (`backend/factor/`) is a monthly Nifty-200 momentum/low-vol paper book per user. **Scoring**
(`backend/scoring/composite.py`) is the one conviction formula (AI ≤ 30%). **Suggestions**
(`backend/suggestions/`) are LONGTERM engine proposals held for a human, with exit rules and alerts.
**Learning** (`backend/learning/`) judges closed paper trades, adds bounded rules, re-tunes params monthly
and asks the LLM for queued ideas. **Builder** (`backend/builder/`) drafts block-spec strategies weekly and
gates them. **Fundamentals screening** (`backend/data/fundamentals/`) gives the fundamentals quality universe for
`quality_momentum`. The code wins over this page. The handbook section is `frontend/src/handbook/trading-and-money.md`
("Long-term ideas", "Strategy builder", "Picks").

## Files

| path | role | key symbols |
|---|---|---|
| backend/forecast/picks.py | Daily Picks job: compute, store, score, forward record, live gate | `picks.py::compute`, `::score`, `::forward`, `::live_refusal`, `::load`, `::ensure_indexes`, `::run`, `::MAX_PICKS`=10, `::MIN_FORWARD`=100, `::CALIBRATION_GAP`=0.05, `::HISTORY_START`, `::CAVEATS` |
| backend/forward/store.py | Forward record store (`forward_records`), idempotent writes that never raise | `store.py::ForwardStore` (`record`, `due`, `set_outcome`, `list`, `scored`, `ensure_indexes`), `::record_id`, `::COLLECTION` |
| backend/forward/scorecard.py | Per source/name stats, the one proven rule, comparison with each existing money gate | `scorecard.py::stats`, `::label`, `::scorecard` (cached 60 s, `force` bypasses; admin id and account size looked up once per call), `::_gate`, `::MIN_N`=100, `::MIN_T`=2.0, `::MAX_GAP`=0.05 |
| backend/forecast/setups.py | 5 setups as pure functions over a wide bar table (no look-ahead) | `setups.py::table`, `::SETUPS`, `::BY_NAME`, `::Setup`, `::momentum`, `::low_vol`, `::momentum_vol`, `::breakout`, `::pullback`, `::_top_decile`, `::_month_starts` |
| backend/forecast/study.py | Event study + per-year walk-forward calibration (years from `lab.splits.yearly_folds`) | `study.py::net_return` (= `lab/assumptions.py::round_trip_return`, 10 bps slipped), `::kept`, `::outcome`, `::events`, `::stats`, `::walk_forward`, `::run`, `::NOTIONAL`=1e5, `::MIN_PRIOR`=30, `::MIN_N`=100 |
| backend/ml/features.py | Research only, not wired (see evaluate.py): 24 price/volume features and net-return labels for the ML harness (no look-ahead; labels via `lab/assumptions.py::round_trip_return`, DEFAULT costs; needs lightgbm) | `features.py::FEATURES`, `::features`, `::labels`, `::long_table`, `::STEP`=5 |
| backend/ml/evaluate.py | Research only, run by hand: purged yearly folds, LightGBM (native API, no scikit-learn) regressor on excess + classifier on P(up); rank IC per year, Brier skill, top decile vs `mom_vol` (momentum_vol_60's score) net of round trips; pass bar; records `lab_runs` kind `ml`. CLI `docker exec neotrade-jobs nice python -m backend.ml.evaluate [--horizon 20]`. The old `forecast/research/ml_experiment_tool.py` is removed | `evaluate.py::HORIZONS`=(20, 60), `::PARAMS`, `::split`, `::rank_ic`, `::ic_t`, `::top_decile_net`, `::evaluate_table`, `::evaluate`, `::passes`, `::run`, `::main` |
| backend/forecast/research/bandit_experiment_tool.py | Research only, not wired: LinUCB/Thompson sizing (0/0.5/1) and exit (horizon vs ATR trail 1.5/2/3) over Picks events; failed its bar 2026-10-18 (fixed rule +0.91% vs bandits +0.68-0.82%), trailing stops lost every year | `bandit_experiment_tool.py::event_table`, `::walk_forward`, `::EXITS` |
| backend/routers/picks.py | `/picks` admin-only API | `routers/picks.py::router`, `::picks_today`, `::picks_history`; order = `forecast/picks.py::rank_key` (also used by `/today` `picks_top`) |
| backend/factor/model.py | Pure momentum + low-vol scoring, selection with buffer, inverse-vol weights, trend/vol exposure | `factor/model.py::Params`, `::scores`, `::select`, `::weights`, `::exposure`, `::target_book`, `::volatility`, `::YEAR/HALF/MONTH` |
| backend/factor/backtest.py | Daily MTM backtest: decide on close, trade next close, real charges + slippage (`simulate(..., ex=lab.assumptions.DAILY)`) | `factor/backtest.py::simulate`, `::_trade`, `::performance` (adds `summary`), `::rebalance_days`, `::equal_weight`, `::buy_and_hold`, `::Result`, `::RISK_OFF_YIELD`=0.065 |
| backend/lab/splits.py | Shared walk-forward folds: one per calendar test year, optional rolling window, purge/embargo trading days | `splits.py::Fold`, `::yearly_folds` |
| backend/factor/validate.py | Walk-forward variant selection (folds from `lab.splits.yearly_folds`, rolling `in_sample_years` window) + deflated Sharpe | `factor/validate.py::grid`, `::walk_forward`, `::deflated_sharpe`, `::WalkForward`, `::TRIALS_TRIED`=16 |
| backend/factor/report.py | CLI `python -m backend.factor.report [--save]`: OOS verdict vs benchmarks | `factor/report.py::verdict`, `::run`, `::_save`, `::DSR_THRESHOLD`, `::MIN_OOS_YEARS`=8 |
| backend/factor/data.py | Nifty 200 CSV universe + yfinance closes, disk cache 20 h | `factor/data.py::universe`, `::closes`, `::series`, `::MARKET`, `::BENCHMARKS`, `::CACHE_DIR` |
| backend/factor/paper.py | Per-user paper factor book, monthly rebalance | `factor/paper.py::rebalance`, `::due`, `::params_for`, `::FactorBookStore`, `::summary_text`, `::PARAMS`, `::SMALL_ACCOUNT`, `::STRATEGY` |
| backend/factor/survivorship.py | CLI that measures survivorship bias (prints only) | `factor/survivorship.py::main` |
| backend/factor/nifty200.csv | Today's Nifty 200 list (survivorship-biased) | read by `factor/data.py::universe` |
| backend/scoring/composite.py | The only conviction formula | `composite.py::AI_CAP`=0.30, `::RULE_FLOOR`=0.45, `::CompositeScore`, `::score_intent`, `::is_bearish` |
| backend/suggestions/scan.py | Replay ~400 d through the engine, record only the last session's LONGTERM proposals | `scan.py::scan_universe`, `::_ArmOnFinalSession`, `::_ArmedOnlyRedis`, `::LOOKBACK`, `::MAX_PENDING_LONGTERM`=5 |
| backend/suggestions/sink.py | Engine `order_sink`: LONGTERM → suggestion, intraday passes through | `sink.py::SuggestionSink`, `::GATED_MODE` |
| backend/suggestions/store.py | `suggestions` collection CRUD, atomic decide, expiry, top-N | `store.py::SuggestionStore` (`create`, `decide`, `settle`, `attach_thesis`, `keep_best`, `expire_stale`, `has_pending`, `list`, `get`), `::DEFAULT_TTL`=3 d |
| backend/suggestions/service.py | Fill an order on paper, or place live and poll | `service.py::execute_suggestion`, `::fill_on_paper`, `::_book`, `::execute_option_suggestion_live`, `::execute_live_order`, `::LIVE_FILL_CHECKS`=5 |
| backend/suggestions/exits.py | Stop/target/trailing/max-hold exit reasons; alerts for own account | `exits.py::exit_reasons`, `::check_exits`, `::breach`, `::max_hold_due`, `::held_too_long`, `::trail_level`, `::_trail_from_bars` |
| backend/suggestions/thesis.py | LLM thesis + AI-half rescore after save | `thesis.py::attach_theses`, `::_thesis_text`, `::_rescored`, `::MAX_PER_SCAN`=10 |
| backend/suggestions/notify.py | Telegram text for proposals/exits | `notify.py::notify`, `::proposals_text`, `::exits_text` |
| backend/routers/suggestions.py | `/suggestions` inbox API | `routers/suggestions.py::scan_now`, `::list_suggestions`, `::reject_suggestion`, `::approve_suggestion_live`, `::_approve_equity_live`, `::_require_strategy` |
| backend/learning/attribution.py | Pure: closed trades grouped by all/regime/reason/strength, shrunk expectancy | `attribution.py::attribute`, `::regime_on`, `::shrunk`, `::net`, `::MIN_TRADES`=10, `::PRIOR_TRADES`=10, `::STRENGTH_BUCKETS` |
| backend/learning/adapt.py | Nightly bounded rules (pause/floor/regime) + `LearnedRules` read by the runner | `adapt.py::learn`, `::decide`, `::load_rules`, `::LearnedRules.blocks`, `::_closed_trades`, `::PAUSE_AFTER`=30, `::FLOOR_STEP`=0.05, `::FLOOR_CAP`=0.8 |
| backend/learning/retune.py | Monthly param re-tune in a `nice` subprocess | `retune.py::retune_strategy`, `::run_all`, `::current_params`, `::start_if_due`, `::variant`, `::_sharpe`, `lab/metrics.py::daily_returns` (was `_daily`), `::summary` (empyrical metrics), `::_Memo`, `::MIN_DSR`=0.95, `::WINDOW_DAYS` |
| backend/learning/hypotheses.py | LLM proposes param ideas; queued, tested like re-tune variants | `hypotheses.py::propose`, `::validate`, `::test_queued`, `::BOUND`=4.0, `::MAX_PER_RUN`=3 |
| backend/learning/library.py | Strategy library cards (card + gate + paper + learned + stats) | `library.py::catalog`, `::strategy_names`, `::_strategies` |
| backend/learning/report.py | Learning snapshot + Friday Telegram note | `report.py::snapshot`, `::weekly_text`, `::facts` |
| backend/builder/draft.py | Weekly drafting job + one-draft test | `draft.py::run`, `::_run_horizon`, `::_test`, `::test_one`, `::start_if_due`, `::_make_room`, `::_retire_paused`, `::_since`, `::_benchmark`, `::MAX_DRAFTS`=3, `::MAX_ACTIVE`=5 |
| backend/builder/validate.py | Only gate between model output and the interpreter | `validate.py::validate_spec`, `::_validate_swing`, `::_is_dup`, `::slugify`, `::describe` |
| backend/builder/store.py | `built_strategies` + `builder_runs`, active-spec cache refresh | `store.py::refresh`, `::ensure_indexes`, `::visible`, `::trial_sharpes`, `::history_of`, `::horizon_of`, `::regime_of`, `::set_status` |
| backend/builder/__main__.py | `python -m backend.builder [--test <slug>]` | `__main__.py::_main` |
| backend/data/fundamentals/scores.py | Pure Piotroski-lite (0–5) + quality score | `scores.py::piotroski_lite_score`, `::quality_score` |
| backend/data/fundamentals/universe.py | Concurrent snapshot fetch → {symbol: score ≥ 0.5} | `universe.py::build_quality_universe` |
| backend/data/fundamentals/protocols.py | Snapshot model + provider protocol | `protocols.py::FundamentalSnapshot`, `::FundamentalsProvider` |
| backend/data/fundamentals/yfinance.py | yfinance-backed provider; D/E is really debt/cash | `yfinance.py::YFinanceFundamentalsProvider`, `::_debt_to_equity` |

## Data

Mongo collections (writer → readers):
- `picks`: `_id` `"<date>:<setup>:<symbol>"`, `date`, `symbol`, `setup`, `label`, `horizon`, `due_date` (`market_calendar.add_trading_days(h+1)`, skips NSE holidays), `entry_ref`, `expected{median,p10,p90}`, `p_up`, `p_beat_nifty`, `n`, `median_excess`, `edge`, `explanation`, `strength`, `created_at`, `outcome` (None until scored → `{exit_date,gross,net,nifty,won,beat_nifty}`), `scored_at`. Insert-only for new ids (`forecast/picks.py::run`). Readers: `routers/picks.py`, `autopilot/picks.py`. Indexes `date`, `outcome` (`forecast/picks.py::ensure_indexes`; must be called at startup in server.py).
- `lab_runs`: one best-effort `kind="study"` run per setup each pass (`forecast/picks.py::_record_runs`: event stats + walk-forward, fingerprint of the close table; `lab/runs.py::LabRunStore`, never raises). The gate backtest, factor report (`--save`), re-tune and builder write `engine`/`factor` runs the same way. `python -m backend.lab rerun <id>` (`lab/__main__.py::rerun`) rebuilds a `factor` or `study` run's inputs from its stored window/config (rows after the window are cut), re-runs and compares fingerprint + every metric within 1e-6; exit 0 same, 1 differs, 2 other kinds ("not re-runnable here"). Data is injectable via `sources` for tests; factor config stores `start` so the re-run reproduces `factor/report.py::run`.
- `forward_records`: `_id` `"<source>:<name>:<symbol>:<YYYY-MM-DD>:<side>"`, `source` (`picks|engine|suggestion|news`), `name`, `user_id`, `symbol`, `side`, `decided_at`, `intraday`, `ref_price`, `horizon_days`, `due_date`, `predicted`, `nifty_ref` (engine only: NIFTY at decision time, None when Redis is unavailable), `outcome` (None until scored; `{void:"no bars"}` has no `excess`, so `scored()` (`{"outcome.excess": {"$exists": True}}`) and `stats` skip it), `scored_at`. Insert-only via `$setOnInsert` (`forward/store.py::ForwardStore.record`). Indexes `(outcome,due_date)`, `(source,name,decided_at)` (`ensure_indexes`, called from `server.py::ensure_collection_indexes`).
- `picks_study`: single doc `_id: "latest"` `{as_of, setups:[stats + walk_forward]}` (`forecast/picks.py::run`).
- `factor_books`: `_id` = `user_id`, `user_id`, `cash`, `shares{sym:int}`, `start_equity`, `started_at`, `start_nifty`, `costs`, `last_rebalance`, `updated_at`, `last_summary` (`factor/paper.py::FactorBookStore`).
- `suggestions`: see `suggestions/store.py::SuggestionStore.create`: `id` (uuid, unique index), `user_id`, `run_id`, `symbol`, `mode`, `side`, `quantity`, `entry_ref`, `stop`, `target`, `max_hold_days`, `trail_atr`, `notional`, `option_contract`, `strength`, `reason_codes`, `strategy`, `score{rule,ai,final}`, `ai_thesis`, `source` (`scan`/`manual`/`scheduler`/`news`/`run`), `status`, `created_at`, `expires_at`, `decided_at`, `reason`, `order_id`. Later fields: `expired_reason:"outranked"` (`keep_best`), `venue`, `filled_quantity` (`settle`), `ai_order` (set by `engine/autorun.py`). Index `(user_id,status,mode)` (`store.py::ensure_indexes`, called at `server.py:125`).
  Statuses: `PENDING`, `REJECTED`, `EXPIRED`, `SENDING` (approve-live claim), `SENT`, `EXECUTED`, plus `APPROVED` (in `DECIDED_STATUSES` only).
- `paper_trades` (owned by the ledger): read by `learning/adapt.py::_closed_trades` (`venue:"paper"`, `status:"CLOSED"`, `strategy` set); `suggestions/exits.py` writes `trail_stop`, `alerted` ($addToSet) and closes `status:"CLOSED", exit_reason:"sold"` directly.
- `learning_state` (one per `user_id`): `paused{name:since}`, `floors{name:float}`, `skip_regimes{name:[up|down]}`, `reset_at{name:dt}`, `regime` (`adapt.py::learn`). Also read by `builder/draft.py::_retire_paused`.
- `learning_changes`: `{strategy, rule (pause|resume|floor|regime), before, after, evidence, user_id, at}`.
- `strategy_retunes`: one doc per attempt `{strategy, current, params, accepted, reason, trials, trial_sharpes, train, test, dsr, at, source?, hypothesis_id?}`; latest `accepted:true` per strategy = running params (`retune.py::current_params`).
- `retune_runs`: `{month:"YYYY-MM", started_at}` claim (`retune.py::start_if_due`, upsert claim, unique index on `month` via `retune.py::ensure_indexes`, called from `server.py::ensure_collection_indexes`).
- `strategy_hypotheses`: `{id, strategy, params, rationale, status: queued|accepted|rejected, created_at, reason, tested_at}`.
- `built_strategies`: `slug` (unique), `owner_id` (None = AI/global), `spec`, `thesis`, `description`, `drafted_at`, `status` (`testing|rejected|active|retired`), `verdict`, `metrics{year,holdout,benchmark?}`, `trials`, `sharpe`, `trial_history`, `tested_at`, `raw` (refused specs). `builder_runs`: `{week:"%G-W%V"}` unique (`builder/store.py::ensure_indexes`).
- `strategy_backtests`: gate rows written via `risk/backtest_gate.py::BacktestGateStore.record` (`strategy_name`, `run_at`) by `builder/draft.py::_test`; read by `adapt.py::learn` (resume) and `library.py::catalog`. `factor/report.py::_save` writes the same `strategy_name`/`run_at`/`passed` keys plus a `report`.
- `daily_bars` (via `datalayer/bars.py::read`): Picks, swing builder, trailing stops.

Redis keys:
- `scan:{user_id}` rate limit 5 / 600 s (`routers/suggestions.py::scan_now`).
- `builder:lock` NX, TTL 6 h (`draft.py::LOCK`); `builder:test:{slug}` NX, TTL 3600 s (`draft.py::test_one`).
- Sentiment / `analyst_verdict:<SYM>` read during scans (`scan.py::_ArmedOnlyRedis` lets only the armed session read sentiment).
- Job status via `system/jobs.py::mark(redis, jobs.BUILDER, ...)`.

Prefs (`backend/prefs.py`): `universe`, `account_size`, `max_exposure`, `per_trade_cap`, `scan_enabled`, `omniroute_model` (thesis model), `factor_paper_capital` (₹3 L), `live_strategies` (library), `autopilot_enabled/live/news`, `picks_live`.
App settings: `app_settings.lab_on(...)` gates "nightly learning", "the monthly re-tune", "the weekly strategy builder".
Disk: `FACTOR_CACHE_DIR` (default `/tmp/neotrade-factor`) pickles, 20 h (`factor/data.py::CACHE_SECONDS`); the file name carries a sha1 of the sorted symbols, stable across restarts (it was Python `hash`, which changes per process).

## Flows

**1. Picks daily (16:00 pass)**
1. `scheduler.py::run_daily_jobs` → `forecast/picks.py::run(db, now)`.
2. `picks.py::load`: every symbol in `daily_bars` + NIFTY from `HISTORY_START` (bars.DEEP_START, 2009) → `setups.py::table` (NIFTY days as calendar).
3. `picks.py::compute` (in `asyncio.to_thread`): `study.py::run` → per setup `signals` → `study.py::events` (entry t+1 open, exit close t+1+H, net of 10 bps slippage per side (`lab/assumptions.py`) and CNC charges on ₹1 L, NIFTY over the same window, `kept` drops overlaps) → `stats` + `walk_forward`.
4. Picks = setups with `n ≥ MIN_N` whose last kept signal is today. Sorted by `median_excess × p_beat_nifty`, then `strength`. Top 10.
5. Upsert `picks_study/latest`. Insert only new `_id`s with `outcome: None`. Then every `outcome: None` pick is scored by `picks.py::score` once its exit bar exists.
5a. Writers (all best-effort, exceptions log only): `picks.py::_forward` writes one `picks` record per new pick (`predicted={p_up, median}`, horizon = setup horizon, user `system`); `suggestions/sink.py::SuggestionSink._forward` writes after `store.create` (source `news` -> `news` record, horizon 5, name `news` until proposals carry a theme; else `suggestion`, name = `order.strategy_name` (or `unknown`), horizon `max_hold_days` or 20); engine entries come from `runner.py::_forward` (see trading-engine).
5b. Right after `picks.run`, `forward/score.py::score_due(db, now)` scores due forward records (`ForwardStore.due` → `outcome(t, record)` on the table: next-open entry, horizon-day close exit, intraday = `ref_price` to same-day close, SELL = short side with `excess = net + nifty`, net via `round_trip_return`; intraday NIFTY return = record `nifty_ref` to the day close, falling back to the day open when `nifty_ref` is missing (morning move leaks into excess); `{"void": "no bars"}` after 10 trading days) and marks `job:last:forward`. Never raises.
6. Trading them is outside this area: `autopilot/picks.py::enter` (09:20 morning pass) and `::exit_due`. Live money needs `picks.py::live_refusal` → None plus prefs `picks_live` and `autopilot_live` (`autopilot/picks.py::live_allowed`).

**2. Long-term scan → suggestion**
1. Triggers: `scheduler.py::run_daily_jobs` (source `scheduler`, users from `prefs_store.scan_enabled_users`), `routers/suggestions.py::scan_now` (`manual`, background task), `datalayer/reactor.py::_scan_user` (`news`), and `engine/autorun.py` catch-up.
2. `scan.py::scan_universe`: resolves instruments, then cached analyst verdicts, `data/fundamentals/universe.py::build_quality_universe(StoreFundamentals)`, `nifty200_sectors()` (failure → `{}`), and builds the LONGTERM strategies with `learning/retune.py::current_params` and `builder_store.regime_of`.
3. Bars come from `HistoricalFeed(StoreHistoryProvider)` over `LOOKBACK` (400 d). `engine/runner.py::run` replays with `order_sink=SuggestionSink(held=mine_holdings)` and `learned=adapt.load_rules`.
4. In the runner, `scoring/composite.py::score_intent` (None below RULE_FLOOR) and `LearnedRules.blocks` apply. `SuggestionSink.__call__` records only when `armed` (final session). An equity SELL is allowed only up to `held`. One PENDING per (user, symbol, mode) (`store.has_pending`). → `SuggestionStore.create` (+ WS `suggestions/created`).
5. `store.keep_best(user, "LONGTERM", 5)` expires the rest as `outranked`. It skips docs with `ai_order` set.
6. `thesis.py::attach_theses` (≤10): `ResearchAgent.run(symbol)` under `use_model(prefs.omniroute_model)` → `store.attach_thesis` (text + `_rescored` score; the sentiment sign is flipped for a non-option SELL suggestion, which wins when the stock falls), WS `enriched`.
7. Scheduler: `risk/paper_gate.py::for_mine` filters, then Telegram via `notify.py::proposals_text`.

**3. Decide a suggestion** (`routers/suggestions.py`)
1. Reject: `store.decide(status="REJECTED")`. This is allowed even past `expires_at`.
2. Approve-live: status must be PENDING → `_require_strategy` (409 if no strategy) → `for_mine` (409 unproven) → `KillSwitchStore.is_tripped` (409).
3. Equity (`_approve_equity_live`): `in_session` → refuses SELL → `mine` broker adapter → `mark_price × qty ≤ per_trade_cap` → claim `decide(status="SENDING")` (atomic, PENDING + not expired) → `service.py::execute_live_order` (place, record `live_orders`, poll 5×1 s, `orders.claim`, `_book` venue live, charged `costs.py::fill_costs`) → `store.settle` to `EXECUTED`/`SENT`/`PENDING`.
4. Option: same rails. Exposure is `margin_estimate` or `premium × qty`. It looks up the NFO contract, uses `_options_broker` (needs `supports_options`), then `execute_option_suggestion_live`.
5. There is no paper approve endpoint. The AI account paper-trades proposals itself (`engine/autorun.py::_autopilot_proposals`, commit dff272a).

**4. Exits** (`suggestions/exits.py`)
1. `engine/autorun.py::_longterm_pass` runs every 15-min bucket (Redis NX `longterm:{user}:{day}:{bucket}`) → `check_exits(db, user)`.
2. It takes OPEN LONGTERM BUY trades with `suggestion_id` in book `mine_book(user)`. If a later-day holdings snapshot lacks the symbol, the trade is closed `sold`.
3. `exit_reasons`: trailing stop (ATR from `daily_bars`, raised only, saved as `trail_stop`), then `breach` stop/target (stop wins ties), then `max_hold_due` (weekdays after entry IST date, from 15:15 IST on the due day).
4. Each reason alerts once (`alerted` $addToSet). `notify.py::exits_text` sends to Telegram. Nothing is sold. `autopilot/service.py::check_exits` reuses `exit_reasons` for the AI book.

**5. Factor paper rebalance**
1. `_longterm_pass` morning (≥09:20 IST, once/day) → `factor/paper.py::due` (no book or not this calendar month) → `rebalance`.
2. Loads `data.closes(universe)` + `^NSEI` in a thread. Accrues cash at 6.5 %/yr. `params_for(capital)` returns `PARAMS` (mom=1.0, top 15, buffer 25, vol 0.15), or top 8 equal-cap below ₹2 L.
3. It excludes the user profile's `avoid` and `too_dear` (share price > slot, not held). `model.target_book` → `marks` → whole-share orders, sells first. It skips buys of symbols another strategy holds in the ledger. `service.py::fill_on_paper` (CNC sell beyond held → ValueError, logged and skipped).
4. Saves book + `last_summary`. `summary_text` goes to Telegram.

**6. Nightly learning** (`scheduler.py::_learn`, Lab-gated)
1. For each `paper_trades.user_id`: `adapt.py::learn(db, user, nifty, now)`.
2. Resume: a paused strategy whose latest `strategy_backtests` row (by `strategy_name`, `run_at`) passed after the pause date → `resume`, `reset_at` = now.
3. `attribution.py::attribute(_closed_trades(...))` → `adapt.py::decide`: pause (≥30 trades, shrunk < 0 and PF < 1), regime skip, floor step. Saves `learning_state` (+ today's `regime`) and inserts `learning_changes`.
4. Fridays IST: `report.py::weekly_text` → Telegram (LLM `learning_review` prompt, falls back to plain facts).
5. The runner reads it with `adapt.py::load_rules` → `LearnedRules.blocks(strategy, strength)` (paused / below floor / regime).

**7. Monthly re-tune + hypotheses**
1. Daily pass → `retune.py::start_if_due` (once per month, Lab) → `spawn()` `nice -n 15 python -m backend.learning.retune`.
2. `_main`: `hypotheses.py::propose` (LLM `strategy_hypotheses` prompt, ≤3 valid ideas, each within ×/÷4 of the current value, not in the grid) → `run_all`. For each strategy with a `GRID` and timeframe `1d` (3 y yfinance) or `5m` (1 y broker history, skipped if none): `retune_strategy` trains on the first 2/3 and takes the best Sharpe with ≥20 trades. The test part must have net > max(current, 0) and DSR ≥ 0.95 over every past trial. The result goes to `strategy_retunes`. Then `test_queued` runs the hypotheses.

**8. Weekly builder**
1. Friday IST daily pass → `draft.py::start_if_due` (Lab, `builder_runs` upsert claim per ISO week) → `spawn()` `python -m backend.builder`. Also `POST /system/builder/run`.
2. `draft.py::run`: Redis `builder:lock` → `_retire_paused` (learning-paused ≥30 d) → `backtest_account` (0 → abort) → `_run_horizon` for `intraday`, `swing`.
3. Per horizon it first tests the waiting `testing` drafts, then calls the LLM (`strategy_builder` / `strategy_builder_swing` prompts, one retry with a new line), then `validate_spec` (dedupe vs AI drafts) → insert → `_test`.
4. `_test`: `BlockStrategy` backtest sized by the owner's account. Swing: 300 d warm-up, then `_since` cut. Then gate row `BacktestGateStore.record`. Rejected when: non-finite Sharpe; `passes_gate` fails; holdout net ≤ 0 (90 d intraday / 180 d swing); DSR < 0.95 over the owner's horizon trials; swing doesn't beat `_benchmark` equal-weight B&H minus charges. → `active`, and `_make_room` retires the lowest paper-net AI active above 5.
5. User drafts: `POST /strategies/built` → `draft.py::spawn_test` → `test_one` (own lock, no LLM).

## Jobs and schedules

| When (IST) | What | Trigger | Lock |
|---|---|---|---|
| 16:00 weekdays | expire_stale, scans + theses, `_learn`, re-tune start, builder start, picks.run | `scheduler.py::run_daily_jobs` (`RUN_HOUR`=16) | `scheduler:daily_lock` (2 h); `scheduler:last_pass` for catch-up |
| 09:20+ once/day | factor rebalance if due, picks entries, expire_stale, morning proposals digest, 16:00 catch-up if missed | `engine/autorun.py::_longterm_pass` (`MORNING`) | `longterm:{user}:{day}:morning` NX 24 h |
| every 15 min | `check_exits` alerts, autopilot exits, picks exits | `_longterm_pass` (`EXIT_CHECK_MINUTES`=15) | `longterm:{user}:{day}:{bucket}` NX |
| 1st pass of month | re-tune subprocess | `retune.py::start_if_due` | `retune_runs.month` (atomic upsert claim + unique index) |
| Friday 16:00 | builder subprocess; learning weekly note | `draft.py::start_if_due`; `scheduler.py::_learn` | `builder_runs.week` unique + `builder:lock` 6 h |
| on demand | manual scan | `POST /suggestions/scan` | rate limit 5/10 min |
| on material news | news scan | `datalayer/reactor.py::_scan_user` | — |

## Invariants

- **AI ≤ 30 % of conviction**: `composite.py::CompositeScore.__post_init__` clamps `ai_weight` to `[0, AI_CAP]` on a frozen dataclass and range-checks `rule_score` (0..1) and `ai_score` (−1..1). Tested in `test_composite_score.py`.
- **AI can't rescue**: `composite.py::score_intent` returns None if `intent.strength < RULE_FLOOR`. Sentiment is flipped for bearish trades (`is_bearish`).
- **One conviction formula**: `thesis.py::_rescored` reuses `CompositeScore`. Never add a second blend.
- Learning only tightens: a floor rises by ≤ `FLOOR_STEP`, never past `FLOOR_CAP`, starts at `RULE_FLOOR` (`adapt.py::decide`). Statistics decide, never the LLM (`adapt.py` docstring; `hypotheses.py` only queues; `draft.py` model never decides).
- Hypothesis values must sit within `BOUND` of the current value, for existing keys only (`hypotheses.py::validate`).
- Every per-account record carries `user_id`: `suggestions`, `learning_state`, `learning_changes`, `factor_books`. Exceptions are market-wide: `picks`, `picks_study`, `strategy_retunes`, `built_strategies` (`owner_id`).
- Decide is atomic and owner-scoped: `store.py::SuggestionStore.decide` matches `{user_id, id, status: PENDING}` and, unless rejecting, `expires_at` not ≤ now. `settle` moves only `SENDING`.
- Approve-live never touches the AI account (`_mine_broker` / `_options_broker` use role `mine`). It respects the kill switch (`KillSwitchStore.is_tripped`), `per_trade_cap`, market hours (`engine/autorun.py::in_session`) and the proven-strategy gate (`risk/paper_gate.py::for_mine`).
- After the broker accepts an order, a failed DB write must not read as "not placed" (`service.py::execute_live_order`).
- CNC paper sell beyond held is refused (`service.py::fill_on_paper`). The sink caps an equity SELL to held (`sink.py::SuggestionSink.__call__`).
- Picks are admin-only until SEBI RA registration exists (`routers/picks.py::router` `dependencies=[Depends(require_admin)]`). Nothing reaches Telegram/digests/chat (`picks.py` docstring; PRODUCT.md "Not an advisor").
- No look-ahead in setups: a value on t uses rows ≤ t (`setups.py` docstring; month-start, not month-end, ranking `_month_starts`). Picks are stored before the outcome is known and never overwritten (`picks.py::run` inserts only unknown `_id`s).
- Builder: the model output reaches the interpreter only through `validate.py::validate_spec`. A refused spec is stored as text under slug `invalid*`. A failed test → `rejected`, never left `testing` (`draft.py::_run_horizon.test`, `::test_one`).
- Factor live is not wired (ROADMAP 2026-10-04 section). The factor book is paper only.

## Endpoints

| Method path | Handler | Auth | Response keys read by frontend |
|---|---|---|---|
| GET `/picks` | `routers/picks.py::picks_today` | admin | `date`, `picks[]` (`symbol,label,horizon,edge,explanation,expected{median,p10,p90},p_up,p_beat_nifty,n,entry_ref`), `setups[]` (`label,horizon,n,median,p_up,p_beat_nifty,walk_forward{edge,oos_excess,oos_n,brier,years[]{year,n,predicted_p_up,realised_p_up,mean_excess}}`), `as_of`, `forward{n,status,win_rate,beat_nifty_rate,buckets[]{bucket,n,predicted,realised}}`, `caveats` (`frontend/src/pages/Picks.jsx`) |
| GET `/picks/history?days=1..3650` (90) | `::picks_history` | admin | `picks[]` (`_id,date,symbol,label,outcome`) |
| POST `/suggestions/scan` 202 | `routers/suggestions.py::scan_now` | user | `{started, symbols}`; body `universe` ≤300 |
| GET `/suggestions?mode&status&limit` | `::list_suggestions` | user | suggestion docs filtered by `for_mine` |
| POST `/suggestions/{id}/reject` | `::reject_suggestion` | user | decided doc; 404 if not pending |
| POST `/suggestions/{id}/approve-live` body `{confirm_token}` | `::approve_suggestion_live` -> `::place_live_approval` | user | no token: `{status:'NEEDS_SECOND_TAP', confirm_token, expires_in}`; with it: settled doc (`status`, `reason`, `order_id`, `venue`, `filled_quantity`); 409/400/502/503 errors (403 another user's token) |

Related, outside the globs: `/strategies/built*`, `/strategies/library` (→ `learning/library.py::catalog`), `/strategies/vocabulary`, `/strategies/describe` in `routers/settings.py`; `GET /journal/learning` (→ `learning/report.py::snapshot`, `routers/journal.py::get_learning`); `POST /system/builder/run` (`system/router.py`). Frontend paths: `frontend/src/utils/api.js` `picks`, `suggestions`.

## Gotchas and known issues
- Fixed: `retune.py::start_if_due` claims the month with an atomic `update_one(upsert)` on a unique `month` index (`retune.py::ensure_indexes`); a `DuplicateKeyError` or an existing claim returns False.
- `picks.py::compute` does not require `walk_forward.edge`. Picks from "no edge" setups are stored and badged (`edge: False`), by design (handbook).
- `due_date` counts weekdays only. Exchange holidays push the real exit (`picks.py::compute` comment). `score` uses the NIFTY calendar.
- `/picks` loads every scored pick on each call (`picks_today` `find({"outcome":{"$ne":None}})`). the scan projects only `p_up` and `outcome`. `picks` has indexes on `date` and `outcome` (`picks.py::ensure_indexes`, called at startup).
- At scan time sentiment is usually not cached, so `final ≤ 0.7·rule + 0.15` until `attach_theses` rescores (`thesis.py` docstring).
- `keep_best` uses wall-clock `decided_at`, not `now` (`store.py::keep_best` comment).
- `check_exits` closes a trade as `sold` by writing `paper_trades` directly: the ledger only closes via fills, and this is an inferred broker-side sale with no fill (owner decision: stays out of the ledger). The row is stamped `closed_by:"inferred_from_holdings"` and `TradeLedger` shows "inferred from your holdings". A same-day buy is not checked against holdings (only a snapshot from a later IST day).
- `SuggestionStore.DECIDED_STATUSES` doesn't list `SENDING`/`SENT`. Nothing reads it for those.
- `builder/draft.py::run` drops `builder:lock` in `finally`. A run past 6 h may delete a newer run's lock (`ponytail:` note at `draft.py::run`).
- The builder's gateway response cache replays cut-off replies, hence the single retry with a timestamped line (ac1b363).
- Factor survivorship: backtest results are flattered ~4–8 %/yr (`factor/survivorship.py`, ROADMAP 17.3.1, f5e2044). `factor/data.py` notes NIFTYBEES' bad split, so price indices are the benchmarks.
- The screening "debt_to_equity" is actually debt/cash (`data/fundamentals/yfinance.py::_debt_to_equity`).
- History (recent fixes):
  - a51584a: momentum-over-volatility setup; study reads from 2009.
  - 13b499c: the AI account paper-trades every stored pick.
  - 4842262: Picks introduced.
  - 9af6ed6: Lab switch gates the AI jobs.
  - 1dc8705: learning judges a trade by the regime its run saw (entry day − 1).
  - f36af00: built strategies' PF counted over round trips.
  - 95a7a98: taken ideas (`ai_order`) keep their slot in `keep_best`.
  - 6826814: own-account exits alert only.
  - dff272a: no paper approvals.
  - 9586480: swing max hold sells from 15:15 on the due day.
  - ec45325: trail failures isolated.
  - a04cb83: re-tests count as trials, no test lockout.
  - 7520722: zero-account and non-finite Sharpe guards, atomic weekly claim.
  - ae6d319: a proposal with no strategy can't be approved.
  - 2413404: an expired proposal can be declined, never approved.
  - 3112a10: top-5 pending.

## Tests

| File | Covers |
|---|---|
| backend/tests/test_forecast_picks.py | setups no-look-ahead, study events/kept/walk_forward, picks compute/score/forward/live_refusal, `/picks` admin auth |
| backend/tests/test_autopilot_picks.py | AI-account Picks entries/exits/live gate (`autopilot/picks.py`) |
| backend/tests/test_factor_model.py | `factor/model.py` scores/select/weights/exposure |
| backend/tests/test_factor_backtest.py | `factor/backtest.py` simulate/performance, `factor/validate.py` walk_forward/deflated_sharpe, `report.verdict` |
| backend/tests/test_factor_paper.py | `factor/paper.py` due/rebalance |
| backend/tests/test_composite_score.py | AI_CAP clamp, RULE_FLOOR, bearish flip |
| backend/tests/test_suggestions.py | `SuggestionSink` + `SuggestionStore` (decide guard, expiry, keep_best) |
| backend/tests/test_suggestion_scan.py | `scan_universe` arming, sentiment suppression, keep_best |
| backend/tests/test_suggestions_router.py | reject / approve-live rails (kill switch, cap, hours, gate, SENDING claim) |
| backend/tests/test_execute_suggestion.py | `service.py::execute_suggestion` / fills |
| backend/tests/test_longterm_exits.py | `exits.py` breach, check_exits, trail, max hold |
| backend/tests/test_thesis.py | `attach_theses`, `_thesis_text`, `_rescored` |
| backend/tests/test_learning.py | attribution, `adapt.decide/learn/load_rules`, `report.weekly_text` |
| backend/tests/test_retune.py | `retune_strategy`, `variant`, `run_all` |
| backend/tests/test_hypotheses.py | `hypotheses.validate/propose/test_queued` |
| backend/tests/test_strategy_library.py | `library.py::catalog` |
| backend/tests/test_runner_attribution.py | strategy/context carried to trades (feeds attribution) |
| backend/tests/test_builder_validate.py | `validate_spec`, swing path, dupes, slugify, describe |
| backend/tests/test_builder_store.py | `builder/store.py` refresh, trial_sharpes, visible |
| backend/tests/test_builder_draft.py | `draft.py` run/_test/_since/_benchmark/_make_room/test_one/start_if_due |
| backend/tests/test_builder_api.py | `/strategies/built*` endpoints |
| backend/tests/test_built_strategy.py | `strategies/built.py::BlockStrategy` (spec interpreter) |
| backend/tests/test_screening_fundamentals.py, test_screening_universe.py, test_yfinance_fundamentals_provider.py | screening scores, universe filter, provider mapping |

Not covered by tests: `factor/survivorship.py`, `factor/data.py`, `forecast/research/bandit_experiment_tool.py`, `suggestions/notify.py` (beyond indirect use).
Run: `cd backend && python -m pytest tests/test_forecast_picks.py ...`.
