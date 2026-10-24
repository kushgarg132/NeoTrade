---
page: trading-engine
covers: [backend/engine/**, backend/strategies/**, backend/risk/**, backend/autopilot/**, backend/brokers/**, backend/options/**, backend/data/**, backend/instruments/**, backend/routers/trading.py, backend/routers/broker.py, backend/routers/options.py]
verified_at: 37d23f6
---
# Trading engine

One bar-by-bar loop (`engine/runner.py::run`) serves backtest, paper and live: only the injected `DataFeed`, `ExecutionClient` and `Clock` differ. Strategies emit `Intent`s, `size_intents` scores (`scoring/composite.py::score_intent`, outside this page) and sizes them, then orders go to paper (`SimulatedExecutionClient`), to a real broker via the gated routing client, or to the autopilot. Around the loop: the two gates to live money (`risk/`), the AI account's fenced autopilot (`autopilot/`), broker adapters (`brokers/`), market data feeds/providers (`data/`), the instrument master (`instruments/`), F&O sizing/pricing (`options/`), the daily auto-run (`engine/autorun.py`) and crash-recovery sweeps (`engine/sweeps.py`). LONGTERM intents never execute: they stop at `suggestions/sink.py::SuggestionSink` (outside this page).

## Files

| path | role | key symbols |
|---|---|---|
| `backend/engine/runner.py` | The loop, sizing, square-off, option exits | `runner.py::run`, `::size_intents`, `::Proposal`, `::_opens`, `::_square_off_orders`, `::_option_exit_orders`, `::_plan_exit_orders`, `::entry_context`, `::_forward` |
| `backend/engine/protocols.py` | Contracts | `protocols.py::Strategy`, `::StrategySpec`, `::StrategyContext`, `::DataFeed`, `::ExecutionClient` |
| `backend/engine/context.py` | Bar buffer; no-lookahead `history()` | `context.py::SimpleStrategyContext` |
| `backend/engine/portfolio.py` | In-memory position book (book of record per run) | `portfolio.py::Portfolio.apply`, `::equity` |
| `backend/engine/persistence.py` | Mongo mirror of orders/fills/positions/trades | `persistence.py::LedgerStore`, `::mine_book`, `::venue_filter` |
| `backend/engine/session.py` | IST + 15:15 square-off cutoff | `session.py::IST`, `::is_past_square_off_time`, `::clock` |
| `backend/engine/backtest.py` | Honest backtester over `run` | `backtest.py::run_backtest`; slippage from `lab/assumptions.py::DEFAULT` (`::BACKTEST_SLIPPAGE_BPS` is an alias) |
| `backend/engine/metrics.py` | Max drawdown, Sharpe on realized events | `metrics.py::compute_max_drawdown`, `::compute_sharpe_ratio` |
| `backend/engine/autorun.py` | Minute tick: daily intraday auto-run, long-term pass, plan build, reminders | `autorun.py::tick`, `::_may_start`, `::_longterm_pass`, `::_autopilot_proposals`, `::live_feed_ready`, `::in_session`, `::start` |
| `backend/engine/adopt.py` | New run inherits today's open intraday trades; closes stale | `adopt.py::adopt_intraday`, `::close_stale` |
| `backend/engine/sweeps.py` | 60 s loop: stuck rows + late live fills | `sweeps.py::_loop`, `::start` |
| `backend/engine/stuck.py` | Settle approve-live proposals a crash left SENDING | `stuck.py::sweep_stuck`, `::STALE` |
| `backend/engine/reconcile.py` | Book live orders that filled after first checks | `reconcile.py::reconcile` |
| `backend/engine/broker_recon.py` | Daily broker-to-ledger reconciliation, read-only (16:00 pass) | `broker_recon.py::classify`, `::check_role`, `::reconcile_user`, `::run_all`, `::latest`, `::summary`, `::book_for` |
| `backend/engine/execution/simulated.py` | Paper/backtest fills (MARKET only) | `simulated.py::SimulatedExecutionClient` (`on_bar`, `mark`, `fill_now`) |
| `backend/engine/execution/routing.py` | Per-strategy live/paper dispatch | `routing.py::RoutingExecutionClient._client_for` |
| `backend/engine/execution/broker.py` | Idempotent real-broker client + status poll | `broker.py::BrokerExecutionClient.submit`, `::poll_once` |
| `backend/engine/execution/autopilot.py` | Live engine orders go through the autopilot | `autopilot.py::AutopilotExecutionClient` |
| `backend/engine/execution/live_order_store.py` | `live_orders` store, compare-and-set | `live_order_store.py::LiveOrderStore.claim`, `::pending_for_user`, `::_PENDING_STATES` |
| `backend/engine/execution/costs.py` / `options_costs.py` | Indian equity / option charges | `costs.py::calculate_indian_costs`, `::DP_CHARGE`; `options_costs.py::calculate_options_costs` |
| `backend/strategies/base.py` | Strategy base: params, universe, token map | `base.py::TokenResolvingStrategy`, `::bars_to_dataframe` |
| `backend/strategies/registry.py` | Builds the default set + active built specs | `registry.py::build_default_strategies` |
| `backend/strategies/indicators.py` | Pandas indicators, support/resistance levels, SMA-alignment trend (strategies and `research/quick.py` share it) | `indicators.py::Indicators`, `::SupportResistance`, `::TrendDetector` |
| `backend/strategies/card.py` / `strength.py` | Strategy card model; strength grading math | `card.py::StrategyCard`; `strength.py::ramp`, `::graded` |
| `backend/strategies/intraday/*.py` | 9 intraday strategies (5m) + `gaps.py` helpers | see Strategies table |
| `backend/strategies/longterm/*.py` | 6 long-term strategies (1d) | see Strategies table |
| `backend/strategies/built.py` | Interprets block specs (AI/user built) | `built.py::BlockStrategy`, `::set_active`, `::load_ok` |
| `backend/strategies/blocks/*.py` | Closed block vocabulary, incremental state, regime | `vocab.py::SETUPS/FILTERS/EXITS/SWING_*`, `blocks.py::setup_fires`, `swing.py::setup_fires`, `state.py::SymbolState`, `swing_state.py::SwingState`, `regime.py::regime_by_day` |
| `backend/risk/backtest_gate.py` | Gate 1: stored backtest meets thresholds | `backtest_gate.py::passes_gate`, `::BacktestGateStore` |
| `backend/risk/paper_gate.py` | Gate 2: user's own paper record | `paper_gate.py::paper_record`, `::proven_strategies`, `::for_mine` |
| `backend/risk/gate_backtest.py` | Runs a 1y gate backtest, records it in `strategy_backtests` and (best effort) a `lab_runs` row, kind `engine`, with `lab.metrics.summary` | `gate_backtest.py::backtest_for_gate`, `::intraday_history`, `::backtest_account` |
| `backend/risk/rules.py` | Position-size and exposure helpers used by `size_intents` | `rules.py::RiskRules` |
| `backend/risk/kill_switch.py` | Daily loss trip, persisted | `kill_switch.py::should_trip`, `::KillSwitchStore` |
| `backend/risk/live_confirm.py` | Server-checked second tap for real money on `mine`: one-time 60 s token bound to user, subject, terms hash | `live_confirm.py::issue`, `::redeem`, `::TokenRefused` (`.code` confirm_missing/expired/spent/mismatch/other_user, `.response()`; Telegram logs the code) |
| `backend/autopilot/fence.py` | Pure order fence (every autopilot order) | `fence.py::check`, `::FenceState`, `::trade_cap`, `::round_trip_cost` |
| `backend/autopilot/service.py` | Fence -> fill (paper/live) -> log -> Telegram | `service.py::submit`, `::_submit`, `::_state`, `::check_exits`, `::ledger_user`, `::book`, `::ai_book_query` |
| `backend/autopilot/picks.py` | AI account trades stored Picks (the latest pass only, never `backfilled` ones) | `picks.py::enter`, `::exit_due`, `::live_allowed` |
| `backend/brokers/protocol.py` | The `BrokerAdapter` interface | `protocol.py::BrokerAdapter`, `::BrokerSessionState` |
| `backend/brokers/registry.py` | Only place that lists brokers | `registry.py::BROKERS`, `::get_broker_adapter`, `::UnknownBroker` |
| `backend/brokers/roles.py` | `ai` / `mine` role routing, no fallback | `roles.py::adapter_for`, `::validate_roles`, `::RoleUnavailable` |
| `backend/brokers/kite.py` + `kite_orders.py` | Kite adapter / order+position+holding+trade calls | `kite.py::KiteAdapter`, `kite_orders.py::KiteOrderClient` |
| `backend/brokers/upstox.py` | Upstox v2/v3 REST adapter over the official SDK (`upstox_client` 2.30.0, sync, run in threads); quote and scrip dumps on httpx; option chain | `upstox.py::UpstoxAdapter`, `::_call`, `::_sdk_client`, `::UpstoxHTTPError`, `::option_chain`, `::_option_key`, `::get_trade_history` |
| `backend/brokers/angel_one.py` | Angel One SmartAPI adapter, no streaming, no options | `angel_one.py::AngelOneAdapter` |
| `backend/brokers/expiry.py` / `trades.py` / `holdings.py` | Token TTL math; IST trade-time parsing; ETF tag | `expiry.py::ttl_seconds_until`, `trades.py::parse_ist`, `holdings.py::kind_of` |
| `backend/options/sizing.py` | Lot/collateral sizing of option intents | `sizing.py::size_option_intent`, `::OptionSizingResult` |
| `backend/options/pricing.py` | Black-Scholes, flat margin | `pricing.py::black_scholes_put`, `::estimate_margin`, `::MARGIN_APPROXIMATION_PCT` |
| `backend/options/premiums.py` | Live premium source from Kite/Upstox | `premiums.py::live_premium_source` |
| `backend/options/backtest.py` | Model-priced options for backtests | `options/backtest.py::ModelOptions` |
| `backend/options/resolver.py` | F&O whitelist | `resolver.py::FO_UNDERLYINGS`, `::is_fo_eligible` |
| `backend/data/protocols.py` | `MarketDataProvider` | `data/protocols.py::MarketDataProvider` |
| `backend/data/providers/` | yfinance, Kite REST, daily-bar store | `yfinance_provider.py::YFinanceProvider`, `kite_provider.py::KiteProvider`, `store.py::StoreHistoryProvider` |
| `backend/data/feeds/` | Replay, polling, tick->bar feeds | `historical.py::HistoricalFeed`, `candle_poll.py::CandlePollingFeed`, `polling_live.py::PollingLiveFeed`, `tick_bars.py::TickBarAggregator`, `live_kite.py::KiteTickerFeed`, `live_upstox.py::UpstoxMarketFeed` |
| `backend/instruments/indian_stocks.py` | Default scan universe (mid + small cap lists) | `indian_stocks.py::ALL_SCAN_STOCKS` |
| `backend/data/fundamentals/` | Fundamentals snapshots and quality score (see picks-and-signals) | `universe.py::build_quality_universe` |
| `backend/instruments/` | Mongo instrument master + sources | `master.py::InstrumentMaster`, `loader.py::refresh_instruments*`, `free_source.py::NseEquityListSource`, `kite_source.py::KiteInstrumentSource`, `resolve.py::resolve_symbol`, `models.py::Instrument` |
| `backend/routers/trading.py` | `/trading/*` control plane + `launch_run` | `trading.py::launch_run`, `::_launch_run`, `::build_feed`, `::start_background_run`, `::stop_background_run`, `::_RUNS` |
| `backend/routers/broker.py` | `/broker/*` connect/status | `broker.py::broker_connect`, `::_refresh_instruments` |
| `backend/routers/options.py` | `/options/*` Upstox chains (read only) | `options.py::get_chain`, `::get_expiries`, `::upstox_for` |

## Data

Mongo (all per-account rows carry `user_id`; every `LedgerStore` read filters on it, `persistence.py::LedgerStore`):

| collection | fields that matter | written by / read by |
|---|---|---|
| `paper_orders` | `id`, `user_id`, `run_id`, `symbol`, `side`, `product`, `strategy_name`, `via`, `suggestion_id`, `context`, `status`. Unique `(user_id,id)` | `LedgerStore.record_order/mark_filled`; read by `_open_trade`, `stuck.py`, `reconcile.py` |
| `paper_fills` | `order_id`, `symbol`, `price`, `quantity`, `costs`, `venue`, `timestamp`. Index `(user_id,timestamp)` | `LedgerStore.record_fill` |
| `paper_positions` | one row per `(user_id,symbol)` (unique), `quantity`, `avg_price`, `realized_pnl` | `LedgerStore.snapshot_positions` (every bar), `get_open_positions` |
| `paper_trades` | round trips: `id`, `mode` (MIS->INTRADAY else LONGTERM), `side`, `status` OPEN/CLOSED, `entry_*`, `exit_*`, `realized_pnl`, `realized_base`, `costs`, `strategy`, `via`, `suggestion_id`, `context`, `venue`. **No index** | `LedgerStore._advance_trade/_open_trade`; read by adopt, paper_gate, autopilot `_state`, autorun |
| `live_orders` | `_id`=app Order.id, `broker_order_id`, `status` (SUBMITTED/ACKNOWLEDGED/PARTIALLY_FILLED/...), `filled_quantity`, `average_price`, `role` (`mine`/`ai`/None), `ledger_user`. Index `(user_id,status)` | `LiveOrderStore.record_submitted/claim`; engine rows (`role` None) polled by the run, role rows by `reconcile`; read by `broker_recon.check_role` (today's rows of a role) |
| `broker_reconciliation` | `_id` "<uid>:<day>:<role>", `user_id`, `day` (IST ISO), `role`, `broker`, `status` ok/mismatch/not_checked, `reason`, `mismatches[{kind,where,symbol,...}]`, `counts`, `checked_at`. Index `(user_id,day)` (created by `run_all`) | `broker_recon.py::_store` (replace_one: re-runs idempotent); read by `today.py::_needs_you`, `digest.py::send_postclose`, `GET /today/reconciliation`, `GET /system/reconciliation` |
| `strategy_backtests` | `strategy_name`, `run_at`, `passed`, `result` (BacktestResult). History kept; latest wins | `BacktestGateStore.record/latest/live_eligible` |
| `kill_switch_trips` | `_id`=`user:YYYY-MM-DD` (IST), `reason`, `equity`, `tripped_at` (`$setOnInsert`, never re-armed) | `KillSwitchStore.trip/is_tripped` |
| `autopilot_log` | `user_id`, `at`, `status` FILLED/SENT/REFUSED/FAILED, `side`, `source` chat/engine/factor/news/picks, `reason`, `price`, `mode` | `service.py::_record`; fence counts today's FILLED/SENT BUYs |
| `autopilot_state` | `_id`=user, `tripped_day` (autopilot's own loss trip) | `service.py::_state` |
| `autopilot_shadow` | plan exits on a really-held AI symbol, logged not sent | `trading.py::_plan_shadow_exit` |
| `trading_runs` | via `RunStore` (`runs.py`): `run_id`, `user_id`, `mode`, `status` RUNNING/STOPPED/error, `params.origin` manual/auto, `progress` | `launch_run`, autorun `_may_start` |
| `instruments` | `Instrument` fields; unique `(exchange,tradingsymbol)` and `instrument_token` | `InstrumentMaster` |
| `instrument_meta` | `_id=free_source_refresh`, `last_refreshed_at` (20 h throttle) | `loader.py::refresh_from_free_public_sources` |
| `suggestions`, `user_prefs`, `holding_theses` | read/updated here (`ai_order`, `status` SENDING->SENT/EXECUTED/NEEDS_REVIEW; prefs below) | autorun, stuck, reconcile |

Redis:

| key | TTL | meaning |
|---|---|---|
| `autorun:{slot}` (`slot` = `user` or `user:MODE`) | 150 s, renewed each tick | which worker owns the user's auto run (`autorun.py::_key`, `KEY_TTL_MS`) |
| `launch:{user}:{mode}` | 30 s | one run starting at a time (`trading.py::launch_run`) |
| `autopilot:lock:{user}` | 30 s | one autopilot order at a time across workers (`service.py::submit`, `LOCK_MS`) |
| `plan:build:{user}:{date}` | 1 h | one worker builds the day's plan (`autorun.py::PLAN_LOCK`) |
| `longterm:{user}:{day}:{bucket}` / `:morning` | 30 min / 24 h | once-per-15-min exit check; once-a-day morning pass |
| `levels:{user}:{day}:{bucket}` | 30 min | owner stop/target alerts |
| `login:remind:{user}:{date}:{early\|late}` | 24 h | login reminder dedupe |
| `broker:{user}:{kite\|upstox\|angel_one}:access_token` | until 06:00 / 03:30 / 00:00 IST (`brokers/expiry.py`) | the broker session; its presence = ACTIVE |
| `runs:cancel` (pub/sub) | n/a | cross-worker run stop (`trading.py::stop_background_run`) |
| `job:last:{name}` | n/a | heartbeat via `system/jobs.py::mark` (`autorun`, `order_sweeps`) |
| `market:regime`, `scheduler:last_pass` | n/a | read: regime label + `event_soon` (`service.py::regime_now`), 16:00-pass date (`_longterm_pass`) |

`user_prefs` keys used here (defaults `prefs.py::DEFAULTS`): `account_size` 1M, `max_exposure` 1M, `per_trade_cap` 100k, `daily_loss_limit` 50k (0 = off), `max_trades_per_day` (0 = off), `live_strategies`, `broker_roles`, `autopilot_enabled`, `autopilot_live`, `autopilot_news`, `picks_live`, `auto_paper_intraday`, `auto_paper_longterm`. `app_settings.lab_on("the intraday auto-run" / "the AI game plan build")` gates both experimental jobs (admin Lab switch, default off).

## Strategies

Registered in `registry.py::build_default_strategies` (order: technical_breakout, mean_reversion, macd_crossover, volume_surge, vwap_reversion, orb_breakout, rsi_momentum_scalp, cash_secured_put, gap_and_go, gap_fill_fade, trend_day_pullback, relative_strength_sector; then `quality_momentum` only if both quality args given, `orb_options` only with `option_universe`, `analyst_verdict` only with verdicts; then active built specs not owned by another user). Mode is filtered by the caller (`trading.py::_launch_run`: `s.spec.mode == mode`). Each has `CARD`, `PARAMS`, `GRID` (re-tune variants, `learning/retune.py`).

| name | mode / tf | fires when (`file::class`) |
|---|---|---|
| `orb_breakout` | INTRADAY 5m | close clears opening range (15 min) by 0.3 ATR on vol > 1.5x range avg; stop 1.5 ATR, target 2 ATR; strength 0.65 (`intraday/orb_breakout.py::ORBStrategy`) |
| `orb_options` | INTRADAY 5m | same trigger, F&O whitelist only, emits `option_flavor` LONG_CALL / LONG_PUT (`intraday/orb_options.py`) |
| `vwap_reversion` | INTRADAY 5m | prev bar >= `deviation` (0.6%) off session VWAP and current bar reverts; stop 1 ATR, target VWAP; 0.6 |
| `volume_surge` | INTRADAY 5m | volume > 3x 20-bar avg; side by candle colour; stop 2%, target 5%; 0.6 (shorts allowed) |
| `rsi_momentum_scalp` | INTRADAY 5m | RSI crosses 60 (or 40 down) with jump >= 5 and price vs EMA9; stop 1 ATR, target 2 ATR; 0.55 |
| `gap_and_go` / `gap_fill_fade` | INTRADAY 5m | catalyst-backed gap breaks opening range / no-catalyst gap fails range and is faded (`intraday/gaps.py` helpers; need `catalysts`, `prev_closes`) |
| `trend_day_pullback` | INTRADAY 5m | VWAP side + EMA slope, first EMA dip that holds then clears |
| `relative_strength_sector` | INTRADAY 5m | sector peers (>= `min_peers`) move as group, stock leads/lags; needs `sector_of` |
| `technical_breakout` | LONGTERM 1d | close crosses nearest resistance on vol > 1.5x; graded 0.55-0.95 (`longterm/breakout.py`) |
| `mean_reversion` | LONGTERM 1d | RSI < 30 and below lower Bollinger; graded 0.5-0.9; stop 5%, target 5% |
| `macd_crossover` | LONGTERM 1d | MACD hist sign flip; graded 0.5-0.9; stop 3%, target 6% |
| `quality_momentum` | LONGTERM 1d | 200-SMA cross up within `quality_scores` universe; strength = quality score |
| `analyst_verdict` | LONGTERM 1d | cached bullish LLM verdict above materiality; strength `RULE_FLOOR + AI_CAP*fraction` |
| `cash_secured_put` | LONGTERM 1d | RSI < 30 + below lower band on F&O names; `option_flavor="CSP"` (SELL put, NRML) |
| `built:<slug>` | INTRADAY 5m or LONGTERM 1d (swing) | `built.py::BlockStrategy`: 1 setup + filters + stop/target; one entry/symbol/IST day (intraday); swing spacing `_SWING_GAP`=5 bars; stop ATR-multiple or setup bar/swing low; swing carries `max_hold_days`, `trail_atr` |

Block vocab (`blocks/vocab.py`): setups `orb_break gap vwap_cross rsi_cross ema_pullback volume_spike`; filters `time_window regime_is sector_rs atr_pct price_vs_vwap volume_confirm`; swing setups `breakout_n pullback_ma rsi2_dip gap_hold momentum_rank volume_breakout`, filters `trend_ma regime_is sector_rs atr_pct liquidity`. `regime.py::regime_by_day`: previous Nifty close vs its 200-day mean -> `risk_on`/`risk_off` (never `neutral`; <200 closes -> None). Intraday `SymbolState` resets each IST day (seeded with previous close only) so backtest and live agree (`built.py::BlockStrategy.on_bar`). Cross-section reads (rank, sector RS) need >= `_MIN_CROSS_SECTION`=30 symbols.

## Flows

1. **Start a run** (`POST /trading/start` -> `trading.py::start_trading` -> `::launch_run` -> `::_launch_run`):
   - Redis lock `launch:{user}:{mode}` then `RunStore.list_active` -> 409 if a run of that mode is live (`launch_run`).
   - INTRADAY: load today's plan (`plan/store.py::current`), add plan symbols, drop symbols the user's open LONGTERM trades hold (`_launch_run`, BHEL 2026-10-08 comment).
   - `run(..., forward=engine_recorder(db, user_id, redis))` (`forward/store.py::engine_recorder`): `size_intents` calls it via `runner.py::_forward` for each INTRADAY equity entry (option entries are not recorded: premium vs underlying bars is meaningless) just before `orders.append`, after the order is fully decided; it writes an `engine` forward record (`name`=strategy, horizon 0, `ref_price`=entry, `nifty_ref` read best-effort from Redis `macro:^NSEI`) and an exception only logs. Only `_launch_run` passes it, so backtests and scans write none.
   - Default universe + connected Kite/Upstox -> `options/premiums.py::live_premium_source` and `FO_UNDERLYINGS` fed alongside (not into equity strategies).
   - `build_default_strategies(...)` filtered to the mode; `live_eligible_strategies` (backtest gate) then `paper_records` (paper gate) -> `eligible`.
   - Live routing needs ALL of: `autopilot_enabled` and `autopilot_live`, an ACTIVE `ai` broker (`ai_broker_adapter`), strategy in `live_strategies`, strategy eligible. Then `live_by_strategy[name] = AutopilotExecutionClient`. Otherwise paper.
   - `build_feed`: INTRADAY tries each of `BROKERS` (kite, upstox, angel_one order = dict order) ACTIVE + `ticker_feed()`; else `CandlePollingFeed(YFinanceProvider)`; LONGTERM -> `PollingLiveFeed`.
   - INTRADAY: `adopt.py::adopt_intraday` seeds `portfolio` + `holders`; `close_stale` closes older-day MIS at mark; `day_realized` re-summed from today's closed paper trades (not `via autopilot:`) so a restart does not re-arm the loss limit.
   - `run(...)` coroutine -> `runs.create` -> `start_background_run` (task in `_RUNS`; done-callback marks stopped/error) -> hub publish.
2. **One bar** (`runner.py::run`, per bar from the feed):
   1. yield to loop every 200 bars (`YIELD_EVERY_BARS`); `SimClock.advance`; `ctx.update(bar)`.
   2. Kill switch (needs `daily_loss_limit`, `kill_switch_store`, `ledger`): `is_tripped` else `should_trip(day_realized + portfolio.equity(marks incl. option marks))` -> `KillSwitchStore.trip`.
   3. `execution.on_bar` (duck-typed) then `apply_fills()` BEFORE strategies decide (fills at bar open / backtest stops).
   4. Each strategy whose universe and `timeframe` match runs `on_bar` with `ctx.current_strategy` set (stamps `Intent.strategy`).
   5. `bar.warmup` -> drop intents, no orders. Else: `plan.refresh`; a new plan version may `expand` the run and produce plan exit orders; `size_intents`; then `_square_off_orders` (INTRADAY owner, >= 15:15), `_option_exit_orders`, then plan exits not already closing.
   6. Per order: skip an entry if the ledger already holds that symbol (another strategy/book); mark option price; `ledger.record_order`; `execution.submit`.
   7. `execution.poll_once` (live clients), `apply_fills` -> `Portfolio.apply`, `ledger.on_fill`, holder bookkeeping, `strategy.on_fill`; `ledger.snapshot_positions`; `on_progress`.
3. **Sizing** (`runner.py::size_intents`, per intent in order): `score_intent` (None = drop) -> owner via `strategies_by_name[intent.strategy]` else symbol owner -> one holder per open position -> `learned.blocks` (entries only) -> `plan.blocks` (INTRADAY entries only) -> kill switch blocks INTRADAY only (LONGTERM still reaches the inbox) -> option path (`options/sizing.py::size_option_intent`; INTRADAY needs `option_legs`, before 15:15, one trade per underlying per day, premium margin <= `per_trade_cap`) -> equity path: needs `stop_hint` and a known price; no INTRADAY entry >= 15:15; `risk_pct = BASE_RISK_PCT(1.0) * final * plan.multiplier`; `RiskRules.calculate_position_size`; whole shares; an exit sizes to the held quantity; `per_trade_cap` trims an entry to the room left; cost filter (target gain >= `COST_MULTIPLE`(3) x round-trip charges + 10 bps x2 slippage, counted in `progress["below_cost"]`); `RiskRules.check_exposure_limit` vs `max_exposure`; product MIS (INTRADAY) / CNC; `order_sink` may take ownership (LONGTERM -> suggestion) -> not executed here.
4. **Backtest** (`backtest.py::run_backtest`): `HistoricalFeed` + `SimulatedExecutionClient(slippage `lab/assumptions.py::DEFAULT` 10 bps, fill_on_next_open=True)`; equity stops/targets exit when a later bar's low/high crosses (stop first; gap fills at the open; entry bar checked too); swing: max hold and ATR trail (`suggestions/exits.py::trail_level`); CNC SELL with nothing held is dropped; trades are per fill but `total_trades`/`win_rate`/`profit_factor` are over round trips net of both legs' charges; Sharpe/drawdown from `metrics.py` on per-fill net P&L.
5. **Gate backtest** (`POST /trading/backtests/{name}`, admin -> `trading.py::run_gate_backtest` -> background `risk/gate_backtest.py::backtest_for_gate`): history from admin's Upstox (free, a year of 5m) else Kite else yfinance (60 days, cannot pass); asks `LOOKBACK_DAYS`=372; sizes with the admin's prefs (`backtest_account`); passes live's `datalayer.bars.prev_closes` per weekday so the gap strategies can fire; a 0-trade run is stored with `reason` "no trades in window"; `orb_options` uses `ModelOptions` + NFO lot sizes; `BacktestGateStore.record` -> `passes_gate`: window >= 365 d, trades >= 30, PF >= 1.3, max DD <= 15%. `GET` same path returns latest minus `trades` (a `built:` slug only for its owner).
6. **Auto run** (`autorun.py::tick`, every 60 s on every worker, `start`): `runs.close_orphaned`; `login_reminders`; pre-market digest; weekly report (`reports/weekly.py::send`, Sundays from 18:00); holding notes (`summaries/holding.py::run_all`); `_preopen_plans` (08:45 to close, lab on, live feed ready, lock) -> outside 09:15-15:30 trading days stop local runs; stop runs whose pref went off; for users with `auto_paper_longterm`/`autopilot_enabled`/autopilot or `:mine` open trades run `_longterm_pass`; owner stop/target `_level_pass`; for each enabled slot: renew key if our run alive, else `_may_start` (live feed ready via `STREAMING_BROKERS`, plan not `skip_day`, no manual ACTIVE run today, user did not stop today's auto run, < `MAX_STARTS_PER_DAY`=5 non-orphaned starts) + `SET NX autorun:{slot}` -> `trading.launch_run(origin="auto")`.
7. **Long-term pass** (`autorun.py::_longterm_pass`): every 15-min bucket: `suggestions/exits.py::check_exits`, `autopilot/service.py::check_exits`, `autopilot/picks.py::exit_due`. Once a day from 09:20: catch-up 16:00 pass if `scheduler:last_pass` older than the previous trading day (`asyncio.create_task(_catch_up)`, not inline), monthly `factor/paper.py` rebalance, `picks.enter`, `store.expire_stale`, pending proposals -> `_autopilot_proposals` (autopilot on) -> `risk/paper_gate.py::for_mine` -> Telegram.
8. **Autopilot order** (`service.py::submit`): per-process `asyncio.Lock` + Redis lock (50 x 0.2 s) -> `_submit`: prefs; `live = autopilot_live` unless `order.live` set (exits use the book that holds the position); price from `marks.mark_prices(max_age=20 s)` (no price -> REFUSED); `fence.check(order, price, _state(...), prefs)`; live -> `adapter_for(user,"ai")` (`RoleUnavailable` -> REFUSED); order carries `via="autopilot:<source>"`, `strategy_name = strategy or "autopilot:<source>"`; live: `suggestions/service.py::execute_live_order(role="ai")`, status FILLED/SENT; paper: `fill_on_paper` into `book(user, live)`; `_record` -> `autopilot_log`, hub, Telegram (unless `quiet`).
9. **Live order follow-up**: `LiveOrderStore.record_submitted` on place; the engine's own client polls `pending_for_user` (rows with `role` not in mine/ai) each bar (`BrokerExecutionClient.poll_once`); role rows are polled by `reconcile.py::reconcile` every 60 s on both workers; both use `LiveOrderStore.claim` (find_one_and_update on status + filled_quantity) so a fill is booked once; reconcile books via `suggestions/service.py::_book` to `ledger_user` and flips SENT suggestion to EXECUTED.
10. **Broker connect** (`POST /broker/{broker}/connect` -> `broker.py::broker_connect`): `adapter.connect(**fields)` (Kite/Upstox `request_token`; Angel One `client_code`+`password`+`totp`); RuntimeError -> 400, KeyError -> 422, other -> 502; then background `_refresh_instruments` (NSE+BSE, then NFO) via `instruments/loader.py::refresh_instruments_from_adapter`. Token stored in Redis with broker-specific expiry.
11. **Option chain** (`GET /options/expiries`, `/options/chain`): needs ACTIVE Upstox (`options.py::upstox_for`, else 409); chain row adds `spot`, `atm_strike`, `pcr` (put OI / call OI).
12. **Instrument master**: startup seeds `seed_nse_equity.json` (`only_new`), then free NSE/BSE/ETF lists (20 h throttle, synthetic tokens `2_000_000_000 + crc32`), then broker dumps overwrite tokens on connect. `upsert_many` reads stored rows once and writes only differing ones in batches of 50 (`master.py::UPSERT_BATCH`).
13. **Daily broker reconciliation** (`broker_recon.py::run_all`, 16:00 pass after `_sync_journals`, skipped on a catch-up pass because brokers serve only today's book): users with `broker_roles`; per role (`mine`, `ai`) the first ACTIVE broker of the role (`reconcile_user`, same pick as `roles.py::adapter_for`), none ACTIVE -> `not_checked` "not checked: logged out"; a raising broker call -> `not_checked` with the error type. `check_role` reads only `get_trades`/`get_holdings`/`get_positions` (never orders). `classify` (pure): broker trades grouped by `order_id` vs today's live fills of `book_for(uid, role)` (`<uid>:mine` / `<uid>:autopilot`) through today's `live_orders` rows of that role (`broker_order_id` -> `_id` -> fill `order_id`): no row -> `unknown_order` (AI account only; hand trades on `mine` are normal), no fill -> `missing_in_ledger`, qty/VWAP (0.5%) -> `quantity_differs`/`price_differs`, a booked fill whose order the broker lacks -> `missing_at_broker` (`where`="ledger"); each broker trade vs `journal_trades` by `trade_id` (`where`="journal"); holdings (non-MF) + positions vs the book's live open quantities (`where`="holdings"): `ai` must match exactly, `mine` only flags broker < book. Same-day CNC sells can read as a holdings difference on a broker that keeps sold shares in holdings until settlement (ponytail note).

## Jobs and schedules

All IST; trading days only (`core/market_calendar.py`: weekends + static NSE holiday set, 2026 official, 2027 provisional).

| when | what | where / lock |
|---|---|---|
| every 60 s, both workers | auto-run tick | `autorun.py::autorun_loop` (started in `server.py` after the orphan sweep); `autorun:{slot}` key |
| every 60 s | stuck-row sweep + live order reconcile | `sweeps.py::_loop`; per-row compare-and-set |
| 16:00 pass, after journal sync | broker-to-ledger reconciliation (today's pass only, not a catch-up) | `scheduler.py::_reconcile_brokers` -> `broker_recon.py::run_all` |
| 08:30, 09:05 | broker login reminders (Telegram) | `autorun.py::_login_reminders`; `login:remind:*` |
| 08:45 -> close | build today's game plan per auto-intraday user with live feed | `autorun.py::_preopen_plans`; `plan:build:*` |
| 09:15-15:30 | intraday auto-run alive; stopped outside | `autorun.py::tick`, `SESSION_OPEN/CLOSE` |
| 15:15 | MIS square-off: runner (per-bar) and autopilot (`service.py::check_exits`) | `runner.py::_square_off_orders`, `session.py::SQUARE_OFF_*` |
| every 15 min in session | long-term/autopilot/picks exits; owner level alerts | `EXIT_CHECK_MINUTES`; `longterm:*`, `levels:*` |
| from 09:20, once/day/user | morning pass: catch-up 16:00 pass, factor rebalance, picks entry, proposals digest | `_longterm_pass`; `longterm:{user}:{day}:morning` |
| Friday night | weekly strategy-builder drafting | `builder/draft.py` (outside this page) |
| 16:00 | daily pass (scan, learning...) | `scheduler.py` (outside; `scheduler:last_pass`) |
| startup | `runs.close_orphaned`, ledger + live order indexes, instrument seed + free-list refresh | `server.py::startup_db_client` |

## Invariants

- No lookahead: `ctx.history` only returns bars already `update`d (`context.py::SimpleStrategyContext`); no `datetime.now` in `engine/`, `core/`, `strategies/` (`tests/test_no_datetime_now.py`); no I/O in `strategies/` (`test_no_network_in_strategies.py`). `_now()` helpers in `execution/broker.py`/`live_order_store.py` dodge the grep via `fromtimestamp(time.time())`.
- Sizing only in `size_intents` + `RiskRules`; strategies never size (`runner.py::size_intents`).
- Any order with no `strategy_name` routes to paper (`routing.py::_client_for`); a priced option contract goes live only through an adapter with `supports_options` (Kite, Upstox; Angel One raises).
- A strategy routes live only if: toggled live AND ACTIVE `ai` broker AND autopilot on+live AND backtest gate AND paper gate (`trading.py::_launch_run`). Live engine orders never go straight to a broker: `AutopilotExecutionClient` -> `service.submit` -> fence. Everything uncertain falls back to paper.
- Only `autopilot/` places orders on the `ai` account, only after `fence.check` (CLAUDE.md exception); nothing routes an AI order to `mine` (`roles.py::adapter_for` never falls back across roles).
- Fence (`fence.py::check`): market open for every order incl. exits; NSE CNC/MIS only; SELL only what the autopilot holds in that product (never short); exits never blocked by caps or the switch; entries need `autopilot_enabled`, no kill trip (`autopilot_state.tripped_day` OR `kill_switch_trips`), no `event_soon`, Nifty 200 (`factor/data.universe`), not already held, not held by another strategy in the same book, notional <= `trade_cap` (halved `risk_off`), deployed + notional <= `max_exposure`, `max_trades_per_day` (0 off), and when the order's `context.expected_return` is set (Picks: `expected.median`, `autopilot/picks.py::enter`; engine/news proposals: target / mark - 1, `autorun.py::_autopilot_proposals`) expected gain >= `COST_MULTIPLE`=1.5 x `round_trip_cost` (both sides' `fill_costs` + 2 x 10 bps slippage); `source=news` also needs `autopilot_news`, not risk-off, <= `NEWS_ENTRIES_PER_DAY`=3. Regime only tightens.
- Kill switch trips once per user per IST day and never re-arms (`$setOnInsert`); blocks INTRADAY entries only; `daily_loss_limit` 0 = off; `day_realized` carried across restarts.
- One run per `(user, mode)` (Redis lock + `RunStore.list_active`); one auto-run owner per slot (`autorun:*`); one open position row per `(user,symbol)` (unique index) so an entry on a held symbol is skipped (`run` step 6).
- Position ownership: only `holders[symbol]`'s strategy may add/exit (`size_intents`); exits close what is held, never flip (`size = abs(held)`).
- Cost realism: backtest 10 bps adverse slippage, next-bar-open fills for equity; paper pays the same 10 bps since 2026-10-24 (intraday paper runs `routers/trading.py` `SimulatedExecutionClient(slippage_bps=DEFAULT, fill_on_next_open=True)`; `Portfolio.equity` (kill switch) is net of `costs_paid`, `paper_trades.net_pnl` = gross - costs (`persistence.py::trade_net` derives it for old rows) feeds every loss limit and win/loss count; every other paper fill `suggestions/service.py::fill_on_paper`, equity only, option premiums keep the mark); live fills are charged the same modelled schedule as paper (`costs.py::fill_costs`; `live_orders` rows store `product`/`option` for late fills, `live_order_store.py::fill_row_costs`; rows from before that book 0).
- Gate thresholds: backtest `MIN_WINDOW_DAYS=365`, `MIN_TRADES=30`, `MIN_PROFIT_FACTOR=1.3`, `MAX_DRAWDOWN=0.15` (`backtest_gate.py`); paper `MIN_PAPER_DAYS=20`, `MIN_PAPER_TRADES=30`, PF 1.3 (None = no losers = pass), net > 0, DD <= 5% of `account_size` (`paper_gate.py::paper_record`).
- Idea gate for the user: `paper_gate.py::for_mine` shows a pending LONGTERM idea only when `proven_strategies`; decided rows always show.
- `venue_filter`: "paper" means "not live", so untagged old rows never leak into the live book (`persistence.py::venue_filter`).
- Ledger namespaces: `user` = AI paper book; `user:autopilot` = AI live book (`service.py::ledger_user`); `user:mine` = orders placed on the user's own account (`persistence.py::mine_book`).
- Plan can only tighten and never touches exits/sizing of exits (`runner.py::size_intents` uses `_opens`); plan exits are paper-only (`_plan_exit_orders` sets no `strategy_name`), AI-account holdings only shadow-logged.
- Multiple workers: all cross-worker decisions use Redis (`SET NX`) or Mongo compare-and-set, never run status (`autorun.py` docstring).

## Endpoints

All behind `get_current_user` at include time (`server.py`: trading, broker, options routers).

| method path | handler | auth | notes / response keys |
|---|---|---|---|
| `POST /trading/start` | `trading.py::start_trading` | user | body `{mode, universe<=300, poll_interval_seconds 1-3600}`; -> `{run_id}`; 409 if already running; 400 no instruments/strategies. Risk caps come from stored prefs, not the body |
| `POST /trading/stop` | `::stop_trading` | user (owner only) | `{run_id}` -> `{run_id, stopped}`; 404 unless the run is the caller's and still `ACTIVE` (a finished run id is 404); cross-worker via `runs:cancel` |
| `GET /trading/runs` | `::list_runs` | user | `RunStore.list_for_user` incl. `progress` (bars, signals, orders, below_cost, last_symbol, last_bar_at, updated_at) |
| `GET /trading/positions?venue=` | `::get_positions` | user | position dicts marked at read time via `marks.mark_prices` (stored `unrealized_pnl` is 0) |
| `GET /trading/kill-switch` | `::get_kill_switch` | user | `{tripped, reason, equity, tripped_at}` |
| `GET /trading/fills`, `/trades`, `/equity` | `::get_fills/get_trades/get_equity` | user | `venue=live` reads the `user:mine` book; `/trades` params `status`, `limit<=1000`, `venue`, `mode`; `/equity` -> `{equity}` realized only (no marks) |
| `GET /trading/instruments?q=&limit=` | `::search_instruments` | user | `InstrumentMaster.search` |
| `POST /trading/backtests/{name}` | `::run_gate_backtest` | admin | 202 `{started, history}` |
| `GET /trading/backtests/{name}` | `::latest_gate_backtest` | user | `{strategy, passed, run_at, ...result minus trades}`; 404 none |
| `GET /broker/list` | `broker.py::list_brokers` | user | `{brokers}` |
| `GET /broker/{b}/status` | `::broker_status` | user | `{state, connected, action}` |
| `GET /broker/{b}/login-url` | `::broker_login_url` | user | `{url}` (null = credential form, Angel One) |
| `POST /broker/{b}/connect` | `::broker_connect` | user | `{state, connected}` |
| `POST /broker/{b}/disconnect` | `::broker_disconnect` | user | `{state, connected:false}` |
| `GET /options/expiries?underlying=` | `options.py::get_expiries` | user | NIFTY / BANKNIFTY; 409 without Upstox |
| `GET /options/chain?underlying=&expiry=` | `::get_chain` | user | `{underlying, name, expiry, spot, atm_strike, pcr, strikes[]}` (strike row: `strike spot pcr call put`, each `ltp close oi oi_change volume bid ask iv delta theta instrument_key`) |

## Gotchas and known issues

Past fixes (from `git log`): `76c312c` reopening keeps a symbol's realized P&L; `45ef82c` next-open fills booked before the bar is decided on; `4107135` backtest stops fill at the gap and on the entry bar; `a6aedf0` replay yields every 200 bars (a year of bars held the loop ~40 s and lapsed the ingest leader lock, 2026-10-15); `216c7ba` exits close what is held, no MIS entry after 15:15; `e5c8d6d` long-term SELL with nothing held is not a short; `3e72111` profit factor over round trips; `73b9b83` option charges at the current NSE schedule; `0ff159b` Upstox refresh keeps only `{exchange}_EQ` rows (a lot-size-less index row KeyError dropped the whole refresh); `86938d2` a 0 loss limit is off and restarts keep the day's realized loss; `1b2c566` late live fills booked, one owner per position; `f490f00` level alerts in their own step; `4ca649a` autopilot exits run with it off, intraday squares off at 15:15; BHEL 2026-10-13: the open trade is matched by side so a SELL does not grow a stale BUY (`persistence.py::_advance_trade`); cap on starts excludes orphaned (deploy-swept) runs so deploys do not strand positions (`autorun.py::_may_start`).

Behaviour that surprises:
- Live fill charges are modelled, not the broker's contract note: live P&L is net of the paper schedule, so it can differ from the broker's by a few rupees.
- Live engine orders report no fill back to the run (`AutopilotExecutionClient.fills` yields nothing); the autopilot's own 15:15 `check_exits` is the only square-off for them (`service.py::check_exits`).
- Daily/swing runs (LONGTERM) never trade: they create suggestions; the `scan` (outside this page) reuses `run` over ~400 days with the sink.
- `HistoricalFeed` filters candles with `historical.py::_within`: aware times compare as instants; if any of `start`/`end`/candle is naive it falls back to wall-clock.
- `PollingLiveFeed` (daily quote as a bar) is wrong for intraday; `CandlePollingFeed` yields closed yfinance 5m candles ~15 min late and marks all but the newest as `warmup` on the first poll or after `add()` (`candle_poll.py`).
- Mid-run plan adds (`plan/expand.py`) need `feed.add`: Kite and Upstox tick feeds have it (`live_upstox.py::UpstoxMarketFeed.add` resolves keys from the adapter's loaded scrip dump; unresolved symbols are logged, not added); polling feeds skip.
- `TickBarAggregator` bars are clock-driven: a quiet symbol still emits a flat zero-volume bar; first window's volume is 0 (no baseline).
- Kite `ticker_feed` probes `ltp` first; a Kite Connect app without market-data permission returns None so `build_feed` falls through to Upstox/polling (`kite.py::ticker_feed`).
- Upstox history is rate-limited by a per-process 0.5 s spacing and 28-day chunks for minute data (`upstox.py::_space_history_call`, `_CHUNK_DAYS`); a gate backtest is ~975 calls.
- Upstox SDK calls go through `upstox.py::UpstoxAdapter._call` (`asyncio.to_thread`, one `ApiClient` per token, `lru_cache` of 8). Its default headers force `Accept: application/json` and the Bearer on every call: the SDK sends `*/*` on some methods and no auth on v3 history. Status is `OrderApi.get_order_status` (`/v2/order/details`); the SDK's `get_order_details` is `/order/history`. Place sends `is_amo: false` (the SDK model requires it). Failures raise `UpstoxHTTPError`, an `httpx.HTTPError`, so `routers/options.py` still answers 502. The quote stays on httpx: the SDK sends `?symbol=`, the API documents `?instrument_key=`.
- `live_upstox.py::decode_feed_response` uses the SDK's generated `MarketDataFeedV3_pb2`; proto3 zeros read as absent (no `ltp` = no tick, no `vtt` = no volume). The transport stays the asyncio `websockets` loop (`::UpstoxMarketFeed._stream`), not the SDK's threaded streamer, so `add()` and resubscribe-on-reconnect keep working.
- LIMIT orders: all three adapters set `SUPPORTS_LIMIT` and send the price (Kite `price`, Angel One `ordertype: LIMIT` + `price`, Upstox); `chat/actions.py::_order_checks` refuses LIMIT on any adapter without it. Kite/Angel One payloads are unit-tested only (no live account).
- Upstox `_PRODUCT_MAP` maps NRML to `D` (delivery/carry-forward); `place_order` for options resolves the key via the option chain, refuses rather than guesses (`_option_key`).
- Position `unrealized_pnl` is never stored non-zero; reads mark at request time (`trading.py::get_positions`), `/trading/equity` does not mark.
- `autopilot/service.py::_state` reads only the latest 1000 trades of the book and counts a SENT (unconfirmed) BUY as deployed/held until reconciled.
- `autorun.py::tick` only runs the long-term/morning pass during 09:15-15:30 (`in_session`); the morning pass is `>= 09:20` and the catch-up for a missed 16:00 pass runs as a background task so the auto-run key does not lapse.
- Options: `size_option_intent` LONG_* needs a live premium (no model fills intraday); CSP/short uses Black-Scholes fallback and flat 15% margin; `options/backtest.py` assumes 5m bars and last-Thursday expiry (NSE moved to Tuesdays), optimistic and not for real orders.
- Instrument tokens from NSE/BSE free lists are synthetic and cannot subscribe to ticks; a Kite sync overwrites them in place (`free_source.py::_synthetic_token`).

Open issues / possible bugs found while reading (not fixed):
- `backend/server.py:147` still indexes `paper_limit_orders`, which nothing reads or writes since the paper ticket was removed (the stuck sweep for it is gone).
- `risk/backtest_gate.py::BacktestGateStore.ensure_indexes` (line 44) and `risk/kill_switch.py::KillSwitchStore.ensure_indexes` (line 30) are defined but never called at startup; `paper_trades` has no index at all (`persistence.py:50-53` indexes only orders, fills, positions).
- `risk/backtest_gate.py:50` and `risk/kill_switch.py:48` call `datetime.now(...)` directly (allowed: `risk/` is outside the grep test), unlike `engine/`.
- `run` still builds `owner_by_symbol` last-writer-wins (`runner.py:492`, `:605`), but it is only a fallback (`size_intents` prefers `strategies_by_name[intent.strategy]`, square-off prefers `holders`) and every run's strategies share one mode (`trading.py` filters by `spec.mode`), so the fallback only ever yields the right mode. Harmless unless a mixed-mode run is introduced.

## Tests

All under `backend/tests/`:

- Runner/engine: `test_size_intents.py`, `test_runner_attribution.py`, `test_runner_kill_switch.py`, `test_runner_warmup.py`, `test_runner_yields.py`, `test_runner_ledger_persistence.py`, `test_mis_square_off.py`, `test_plan_runner.py`, `test_plan_gate.py`, `test_mid_session_adds.py`, `test_run_restart.py` (adopt), `test_strategy_context.py`, `test_portfolio.py`, `test_session.py`.
- Backtest: `test_backtest_e2e.py`, `test_backtest_honest.py`, `test_backtest_metrics.py`, `test_simulated_next_open.py`, `test_options_backtest.py`, `test_historical_feed.py`.
- Execution/ledger: `test_routing_execution_client.py`, `test_broker_execution_client.py`, `test_live_order_store.py`, `test_live_option_orders.py`, `test_indian_costs.py`, `test_options_costs.py`, `test_ledger_store.py`, `test_ledger_venue.py`, `test_ledger_scoping.py`, `test_ledger_timestamps.py`, `test_reconcile.py`, `test_broker_recon.py`, `test_stuck_sweep.py`, `test_trade_lifecycle.py`.
- Autorun/router: `test_autorun.py`, `test_lab_switch.py`, `test_trading_router.py`, `test_broker_router.py`, `test_option_chain.py`.
- Gates/safety: `test_backtest_gate.py`, `test_paper_gate.py`, `test_kill_switch_decision.py`, `test_kill_switch_store.py`, `test_no_datetime_now.py`, `test_no_network_in_strategies.py`.
- Autopilot: `test_autopilot.py` (fence + service), `test_autopilot_execution.py`, `test_autopilot_picks.py`.
- Strategies: `test_strategies_ported.py`, `test_gap_strategies.py`, `test_relative_strength_sector.py`, `test_trend_day_pullback.py`, `test_quality_momentum_strategy.py`, `test_strategy_cards.py`, `test_strategy_library.py`, `test_strategy_strength.py`, `test_built_strategy.py`, `test_blocks.py`, `test_blocks_state.py`, `test_swing_blocks.py`, `test_intraday_options.py`, `test_user_strategies_scope.py`.
- Brokers: `test_broker_registry.py`, `test_broker_roles.py`, `test_broker_expiry.py`, `test_kite_adapter.py`, `test_kite_orders.py`, `test_kite_provider.py`, `test_kite_ticker_feed.py`, `test_kite_instrument_source.py`, `test_upstox_adapter.py` (wire-level parity via `tests/upstox_wire.py`, which fakes httpx and urllib3), `test_upstox_market_feed.py`, `test_angel_one_adapter.py`, `test_broker_portfolio.py`.
- Options: `test_options_sizing.py`, `test_options_pricing.py`, `test_options_resolver.py`, `test_option_premiums.py`.
- Data/instruments: `test_polling_live_feed.py`, `test_candle_poll_feed.py`, `test_yfinance_provider.py`, `test_instrument_master.py`, `test_instrument_loader_kite_refresh.py`, `test_free_instrument_sources.py`, `test_resolve_symbol.py`.
- No direct tests found for: `engine/sweeps.py`, `data/feeds/tick_bars.py` (only via the Kite/Upstox feed tests), `data/providers/store.py`, `routers/options.py` beyond `test_option_chain.py`, `execution/autopilot.py` beyond `test_autopilot_execution.py`.
