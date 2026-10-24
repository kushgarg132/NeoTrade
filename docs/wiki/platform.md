---
page: platform
covers: [backend/auth/**, backend/core/**, backend/configs/**, backend/ws/**, backend/system/**, backend/profile/**, backend/routers/**, backend/server.py, backend/jobs.py, backend/.importlinter, backend/database.py, backend/prefs.py, backend/app_settings.py, backend/locks.py, backend/rate_limit.py, backend/log_redaction.py, backend/broadcast.py, backend/runs.py, backend/marks.py, backend/analytics.py, backend/__init__.py, docker-compose.yml, backend/Dockerfile, backend/.dockerignore, backend/requirements.txt, .github/**]
verified_at: 37d23f6
---
# Platform: app shell, auth, live socket, settings, endpoint map, deploy

The FastAPI process that everything else plugs into: `backend/server.py` builds the app, mounts every router under `/api/v1` behind `get_current_user`, runs the startup that creates indexes and starts every in-process loop, and serves the single WebSocket. This page also owns identity (Google sign-in, session JWT, rotating refresh cookie, admin role), per-user prefs and profile, deployment-wide `app_settings` (LLM model/tiers/feature switches/Lab), the cross-worker bus, the admin system views, shared engine value types (`backend/core`), and how the backend reaches production. Domain logic behind the routers (engine, journal, portfolio, brokers, guardrails, chat, plan) lives on other pages; this one has the complete endpoint map.

## Files

| path | role | key symbols |
|---|---|---|
| `backend/server.py` | app factory, CORS, router mounts, startup/shutdown, `/health` | `server.py::app`, `startup_db_client`, `shutdown_db_client`, `_expand_instruments`, `health` |
| `backend/jobs.py` | the `jobs` process: background loops, `jobs:heartbeat` | `jobs.py::start_loops`, `main`, `heartbeat_age` |
| `backend/database.py` | Mongo (motor, tz-aware UTC) + Redis clients, one global | `database.py::db`, `DatabaseManager`, `mongo_client` |
| `backend/configs/settings.py` | pydantic-settings env config (`.env`, case-sensitive, extras ignored) | `settings.py::Settings`, `settings` |
| `backend/configs/logging_config.py` | coloured stdout logging; uvicorn loggers at DEBUG | `logging_config.py::setup_logging` |
| `backend/auth/dependency.py` | bearer auth + admin gate | `get_current_user`, `require_admin`, `get_user_store` |
| `backend/auth/jwt.py` | HS256 session token, `sub`=user id | `create_session_jwt`, `decode_session_jwt` |
| `backend/auth/google.py` | Google ID-token verification (rejects `email_verified is False`) | `verify_google_token`, `InvalidGoogleToken` |
| `backend/auth/store.py` | `users` collection; role derived from `ADMIN_EMAILS` | `UserStore.upsert_from_google`, `_role_for` |
| `backend/auth/models.py` | `User` model | `auth/models.py::User` |
| `backend/auth/refresh_store.py` | opaque hashed refresh tokens, rotation + replay detection | `RefreshTokenStore.issue/rotate/revoke/revoke_all`, `ROTATION_GRACE` |
| `backend/auth/broker_credentials.py` | per-user Fernet-encrypted broker API keys | `BrokerCredentialStore`, `get_credential_store`, `fernet_from_settings`, `CredentialEncryptionUnavailable` |
| `backend/auth/kite_session.py` | Kite login/token lifecycle, token cached in Redis to 06:00 IST | `KiteSessionManager`, `next_6am_ist`, `_redis_key` |
| `backend/core/clock.py` | `Clock` protocol; engine code must not call `datetime.now` | `SystemClock`, `SimClock` |
| `backend/core/market_calendar.py` | NSE cash-market calendar: weekends + static holiday set (2026 official from NSE's holiday API, 2027 provisional); every "is the market open / last session / due date" check routes here | `is_trading_day`, `previous_trading_day`, `next_trading_day`, `last_trading_day`, `add_trading_days`, `trading_days_between`, `is_last_trading_day_of_week`, `market_phase` (pre/session/post/closed, IST), `next_open` |
| `backend/core/models.py` | engine value types (no I/O) plus market/research models | `Side`, `Bar`, `Intent`, `Order`, `Fill`, `Position`, `BrokerOrderStatus`, `BrokerTrade`, `Holding`, `Venue`; `NewsArticle`, `FinancialEvent`, `CompanyInfo`, `PriceCandle`, `BacktestResult`, `Watchlist`, `Trend` |
| `backend/ws/hub.py` | per-connection bounded queues, topic fan-out, Redis-backed publish | `Hub`, `Connection`, `hub`, `handle_broadcast_event` |
| `backend/ws/routes.py` | `/api/v1/ws` endpoint, actions, streamed LLM work | `stream`, `_handle`, `authenticate_token`, `origin_allowed`, `_BUDGETS`, `_stream_analysis/_quick_analysis/_chat` |
| `backend/ws/pump.py` | 15 s price + P&L push loop | `push_once`, `pump_loop`, `start`, `PNL_TOPIC` |
| `backend/ws/publish.py` | adapter so stores publish without importing the hub | `publisher_for` |
| `backend/broadcast.py` | Redis pub/sub wrapper | `publish`, `listen`, `listen_forever` |
| `backend/runs.py` | durable trading-run records + worker liveness | `RunStore`, `BOOT_ID`, `ALIVE_KEY`, `run_summary` |
| `backend/prefs.py` | per-user preferences with defaults | `DEFAULTS`, `EDITABLE`, `PrefsStore`, `PrefsStore.unset` (clears one field; `update` ignores None) |
| `backend/app_settings.py` | deployment-wide settings + 30 s in-process cache | `AppSettingsStore`, `lab_on`, `feature_enabled`, `current_llm_model`, `TIERS`, `FEATURES` |
| `backend/profile/{models,store}.py` | what a user tells the AI about themselves + memories | `ProfileUpdate`, `ProfileStore`, `MemoryRefused` |
| `backend/system/router.py` | admin-only status, builder trigger, broker reconciliation read, backlog CRUD | `system_status`, `run_builder`, `reconciliation`, `*_backlog_item` |
| `backend/system/schedule.py` | job clock times for UI copy, read from `scheduler.RUN_HOUR/RUN_MINUTE`, `autorun.PLAN_AT/SESSION_OPEN/SESSION_CLOSE/MORNING/EXIT_CHECK_MINUTES`, `session.SQUARE_OFF_*`, `monitor.SESSION_*`; `GET /system/schedule` returns "HH:MM" IST strings | `get` |
| `backend/system/status.py` | handbook live-panel data, 5 blocks, cached 30 s | `build_status`, `cached_status`, `BLOCKS` |
| `backend/system/jobs.py` | `job:last:<name>` Redis hash writer/reader | `mark`, `last_runs`, `LOOPS` |
| `backend/system/data_quality.py` | nightly check (stale bars vs the last trading day's session from 15:45, unlisted, silent feeds; `failures`) + live truth checks (ingest heartbeats > 2x interval (min 120 s) or gone, quotes loop, `scheduler:last_pass`, Picks study, due by 18:00 of the last trading day; LLM provider failing = `llm:last_error` newer than `llm:last_ok` and < 30 min old; trading days only (`_silent_stops`): Lab off, an `auto_paper_intraday` user with no INTRADAY `trading_runs` row today (09:30-15:30 IST) or a RUNNING run with `progress.last_bar_at` > 15 min old, news triage under 20% of its 7-day hourly mean over the last 3 h (08:00-20:00 IST); `engine/autorun.py` heartbeat note says why nothing started) | `check`, `live`, `alerts` (admin Today item, silent on weekends and NSE holidays), `last_trading_day_at`, `watch_loop`/`watch_tick` (jobs, 300 s, lock `data_quality:watch_lock`, state `data_quality:watch`: Telegram to every admin's linked chat when a `live` failure holds 2 ticks, and when it clears; digits ignored when matching) |
| `backend/system/backlog.py`, `seed_backlog.py` | admin backlog store; one-time seed | `ItemIn`, `ItemPatch`, `list_items/create/update/delete`, `seed` |
| `backend/locks.py` | token-checked Redis lock (used by the ingest worker only) | `acquire`, `renew`, `release` |
| `backend/rate_limit.py` | fixed-window per-key limiter, fails open | `allow` |
| `backend/log_redaction.py` | strips `token=` and Telegram bot tokens from logs | `RedactTokens`, `install`, `_PATTERNS` |
| `backend/marks.py` | best-effort current prices (Redis `quote:` then yfinance) | `mark_prices`, `cached_quotes`, `store_quotes` |
| `backend/analytics.py` | P&L cards and the scorecard maths (`compute_scorecard(..., marks)`: with marks each strategy adds `open`, `unrealized`, `total` from `open_by_strategy`, totals add `open`, `unrealized`; `GET /analytics/scorecard` passes `mark_prices` of open symbols) | `compute_pnl`, `compute_scorecard`, `open_by_strategy` |
| `backend/routers/*.py` | HTTP handlers (map below) | one module per area |
| `docker-compose.yml`, `backend/Dockerfile`, `backend/requirements.txt` | runtime image and stack; pinned SDKs `upstox-python-sdk==2.30.0`, `empyrical-reloaded==0.7.0` (backend/lab/metrics.py), `lightgbm==4.6.0` (backend/ml/, native API; no scikit-learn), `aiogram==3.31.0` (caps pydantic below 2.14) | services `backend`, `ingest` (no frontend service; Vercel serves it) |
| `.github/workflows/ci.yml`, `deploy-backend.yml` | CI and push-to-deploy caller | see Deploy |

Router modules by area (handlers in the table): `auth`, `settings` (prefs, strategies, OmniRoute admin, broker creds), `trading`, `suggestions`, `orders`, `chat_actions`, `analytics`, `broker`, `journal`, `guardrails`, `portfolio`, `mine`, `today`, `plan`, `picks`, `profile`, `watchlist`, `options`, `market_data`, `agents`. `backend/__init__.py` is a one-line package marker.

## Data

Mongo (db `DATABASE_NAME`, default `stock_investor_db`; datetimes come back tz-aware UTC via `database.py::mongo_client`):

| collection | fields that matter | indexes | writer / reader |
|---|---|---|---|
| `users` | `id` (uuid), `google_sub`, `email`, `name`, `picture`, `role`, `created_at` | unique `google_sub` (`auth/store.py::ensure_indexes`) | `upsert_from_google` on every login (role re-derived); read by `get_current_user` per request |
| `refresh_tokens` | `token_hash` (sha256), `user_id`, `expires_at`, `revoked_at`, `rotated` | unique `token_hash`; `(user_id, revoked_at)`; TTL on `expires_at` (0 s) | `RefreshTokenStore` |
| `broker_credentials` | `user_id`, `broker`, `api_key_enc`, `api_secret_enc`, `extra_enc`, `api_key_masked` | unique `(user_id, broker)` | settings router writes; broker adapters read |
| `user_prefs` | `user_id` + `prefs.py::DEFAULTS` keys (below) | unique `user_id` | `PrefsStore`; read everywhere (scheduler, engine, guardrails) |
| `user_profiles` | `_id`=user id, `display_name`, `experience`, `risk_appetite`, `styles`, `horizon`, `goals`, `favour`, `avoid`, `constraints`, `about_me`, `answer_style`, `memories[{id,text,source,created_at}]` | none | `ProfileStore`; chat/AI read |
| `app_settings` | one doc `_id:"singleton"`: `llm_model`, `llm_tiers.{fast,standard,deep}`, `llm_features_off[]`, `portfolio_verdicts` ("admin"/"all"), `lab_enabled` | none | admin routes write; `_refresh` reads (30 s) |
| `trading_runs` | `run_id`, `user_id`, `mode`, `universe`, `params`, `status` (RUNNING/STOPPED/ERROR), `boot_id`, `progress`, `started_at`, `stopped_at`, `error` | unique `run_id`; `(user_id, status)` | `RunStore` (trading router, autorun) |
| `backlog` | `title`, `area`, `status`, `rank`, `why`, `notes`, `effort`, `source`, `done_at` | none | admin routes; `seed_backlog` upserts by title |
| `watchlist` | `user_id`, `symbols[]`, `updated_at` | none (see Gotchas) | `routers/watchlist.py`; ingest, plan, news read |
| `portfolio_snapshots` | index `(user_id, at desc)` created at startup (`server.py:161`) | | written by portfolio service (other page) |

Startup also creates indexes for instruments, suggestions, builder, journal, mine thesis, `mine_daily`, guardrails, chat actions, broker credentials, ledger, `live_orders`, `paper_limit_orders` (`server.py::startup_db_client`) and `trading_runs` and `lab_runs` (`lab/runs.py::LabRunStore.ensure_indexes`); `ensure_collection_indexes` also calls `learning/retune.py::ensure_indexes` `forecast/picks.py::ensure_indexes` and `forward/store.py::ForwardStore.ensure_indexes`.

`user_prefs` keys and defaults (`prefs.py::DEFAULTS`, all editable via `PUT /settings/preferences`): `universe` (=`ALL_SCAN_STOCKS`), `account_size` 1,000,000, `max_exposure` 1,000,000, `per_trade_cap` 100,000, `daily_loss_limit` 50,000 (0 = off), `scan_enabled` true, `omniroute_model` null, `live_strategies` [], guardrails (`guardrails_enabled` false, `max_trades_per_day`, `cooldown_after_losses`, `cooldown_minutes` 30, `max_option_trades_per_day`, `max_option_lots`, `warn_naked_options`), `auto_square_off` "off", `factor_paper_capital` 300,000, `broker_roles` {}, `autopilot_enabled/live/news`, `picks_live`, `rebalance_targets`, `auto_paper_intraday/longterm`, `portfolio_max_loss_pct` 25, `portfolio_max_weight_pct` 20, `news_alerts` "held". Note `factor_paper_capital` is in `EDITABLE` but not in `PreferencesPatch`, so the HTTP API cannot set it.

`app_settings` module caches (per process, TTL `_TTL_SECONDS`=30 s, `app_settings.py::_refresh`): `_cached_llm_model`, `_cached_tiers`, `_cached_off`, `_cached_lab`. A write refreshes the local copy at once; other workers catch up within 30 s.

Redis keys owned or written by files on this page:

| key | TTL | owner |
|---|---|---|
| `rate:<name>` (names: `analyze:<uid>` 10/60 s, `quick_analyze:<uid>` 60/60 s, `chat:<uid>` 20/60 s on the socket; `scan:<uid>` 5/600 s; `rebalance:<uid>` 10/60 s; `strategies:submit:<uid>:<IST day>` 3/2 days) | window | `rate_limit.py::allow` |
| `worker:alive:<BOOT_ID>` | 90 s, refreshed every 30 s | `runs.py::keep_alive`, `runs.py::ALIVE_KEY` |
| `launch:<uid>:<mode>` | 30 s | `trading.py::launch_run` (one run per mode) |
| `broker:<uid>:kite:access_token` | until next 06:00 IST | `kite_session.py::KiteSessionManager` (other brokers: brokers/ pages) |
| `quote:<SYM>` JSON `{ltp, prev_close, at}` | 120 s write-through (ingest sets its own) | `marks.py::store_quotes`, ingest `datalayer/prices.py` |
| `job:last:<name>` hash `{at, ok, note}` | none | `system/jobs.py::mark` |
| `telegram:link:<uid>` | 900 s | `routers/guardrails.py::telegram_link` |
| `scheduler:daily_lock` (2 h PX), `scheduler:last_pass` | | `scheduler.py::_run_locked` |
| pub/sub channels `ws:events`, `runs:cancel` | | `ws/hub.py::EVENTS_CHANNEL`, `trading.py::stop_background_run` |

In-process caches: `routers/settings.py::_USAGE_CACHE` (60 s, stale-while-revalidate), `_FEATURE_USAGE` (300 s), `routers/today.py::_STATE_CACHE` (60 s, only when all sessions ACTIVE), `routers/market_data.py::_quote_cache` (60 s, 500 entries), `system/status.py::_CACHE` (30 s).

## Flows

1. **Sign-in.** Browser posts a Google ID token to `POST /auth/google` (`routers/auth.py::google_login`) -> `auth/google.py::verify_google_token` (signature, audience `GOOGLE_CLIENT_ID`, `email_verified`) -> `UserStore.upsert_from_google` (role = admin iff email in `ADMIN_EMAILS`, recomputed each login) -> `create_session_jwt` (30 min) -> `RefreshTokenStore.issue` -> `Set-Cookie neotrade_refresh` (httpOnly, Secure, SameSite=None, `path=/api/v1/auth`, 60 d; `routers/auth.py::_set_refresh_cookie`). Body: `{token, user}`.
2. **Authenticated request.** `HTTPBearer` -> `decode_session_jwt` -> `UserStore.get_by_id` (one Mongo read per request; 401 "Invalid or expired session" / "User no longer exists") -> `require_admin` adds a 403 if `user.role != "admin"` (`auth/dependency.py`). Routers are mounted with `dependencies=[Depends(get_current_user)]` in `server.py`; admin routes add `require_admin` on the handler (or router for `/picks`).
3. **Refresh.** `POST /auth/refresh` reads the cookie only (no bearer) -> `RefreshTokenStore.rotate`: atomic `find_one_and_update` kills the presented token; within `ROTATION_GRACE` (10 s) of a prior rotation a sibling tab gets its own new token; an older replay revokes all of the user's tokens; a plain logged-out token returns None without killing siblings -> new cookie + `{token}`; failure clears the cookie and returns 401. `POST /auth/logout` revokes the cookie's token and clears it.
4. **Startup** (`server.py::startup_db_client`): connect Mongo+Redis -> `hub.attach_redis` -> `asyncio.create_task(broadcast.listen_forever({"ws:events": handle_broadcast_event, "runs:cancel": handle_cancel_broadcast}))` -> ensure indexes (incl. `ensure_collection_indexes`) -> seed instruments (`only_new=True`) and expand NSE/BSE lists in a background task (`_expand_instruments`) -> `builder_store.refresh` -> `AppSettingsStore.load_into_cache` -> `ws_pump.start` -> `RunStore.ensure_indexes`, `runs.keep_alive` task, `close_orphaned(redis)` -> if `RUN_BACKGROUND_JOBS`: `jobs.start_loops` (scheduler, order sweeps, guardrail monitor, Telegram, autorun; after the sweep so its own first run is not swept). The `jobs` container does the same from `jobs.py::main` (cancel listener, keep_alive, orphan sweep, `start_loops`, heartbeat). Shutdown deletes this worker's `worker:alive` key and closes clients.
5. **Live socket.** `GET /api/v1/ws?token=<JWT>`: `ws/routes.py::stream` checks `origin_allowed` (no Origin header allowed; else must be in `CORS_ALLOWED_ORIGINS`) and `authenticate_token`, else closes 1008; accepts, sends `{topic:"system",event:"ready"}`, `hub.connect`, starts `_pump` (forwards the connection queue, a `ping` frame every 20 s idle). Client actions via `_handle`: `subscribe`/`unsubscribe` (topics list), `ping`, `analyze`, `quick_analyze`, `chat`; others return a `system`/`error` frame. The three work actions are rate limited by `_BUDGETS` and run as tasks that `connection.offer` frames on reply topics `analysis:<req_id>`, `quick_analysis:<req_id>`, `chat:<req_id>` (events `started|report|error|done`, chat also `thinking|content|action|suggestions`; `step` and `answer_end` are dropped). Reply topics are delivered directly to the connection, not through subscriptions.
6. **Publish.** Stores call `ws/publish.py::publisher_for(uid)` -> `Hub.publish` JSON-encodes (ObjectId -> str) -> `broadcast.publish("ws:events")`; if Redis is absent or errors, `Hub.deliver` runs locally. Every worker's `broadcast.listen` -> `handle_broadcast_event` -> `Hub.deliver` (match `user_id` and subscribed topic) -> `Connection.offer` (queue 100, drops oldest when full). Topics seen in code: `prices:<SYM>` `tick`; `pnl` `updated`; `trades`/`positions` `changed` (`engine/persistence.py::LedgerStore._emit`); `runs` `started|progress|stopped`; `suggestions` `created|decided|enriched`; `portfolio` `refreshed|worsened`; `guardrails` `breach`; `news` `alert`; `autopilot` `logged`.
7. **Price/P&L pump.** `ws/pump.py::push_once` every `INTERVAL_SECONDS`=15: symbols = `hub.subscribed_symbols()` (this worker's sockets only) -> `marks.mark_prices` -> publish `prices:<SYM>/tick` to `users_watching`; for each user on topic `pnl` build `LedgerStore(db, user_id)` marks and publish `analytics.compute_pnl` plus `paper` and `live` = `{mine, ai}` (`analytics.py::compute_live_pnl`).
8. **Preferences.** `PUT /settings/preferences` (`settings.py::update_preferences`) validates `PreferencesPatch`, drops `None` fields (`exclude_none`, so a field cannot be cleared to null; the goal is removed with `DELETE /settings/goal` → `PrefsStore.unset`), forces `autopilot_enabled=False` when `broker_roles` has no `ai` account, `PrefsStore.update` (only `EDITABLE` keys).
9. **Admin LLM controls.** `POST /settings/omniroute-model|omniroute-tiers|llm-feature|lab` and `PUT /settings/portfolio-verdicts` write `app_settings`; `POST /settings/omniroute-model/test` sends one prompt (`prompts/model_test`) direct to the gateway with a 30 s timeout. `current_llm_model(tier)` resolves tier -> single model -> `OMNIROUTE_MODEL`.
10. **Strategy submit/retest** (`settings.py::submit_strategy`, `retest_strategy`): validate spec -> `_check_caps` (5 active per horizon, one `testing` at a time, `account_size > 0`) -> insert as `testing` (slug retry x3 on `DuplicateKeyError`) -> `_spend_slot` (3 per IST day; over limit deletes the draft / restores `rejected`) -> `draft.spawn_test`.
11. **Start a paper run** (`trading.py::launch_run` -> `_launch_run`): Redis `launch:` lock + one active run per mode -> resolve instruments (intraday adds game-plan symbols, drops long-term holdings) -> build strategies -> backtest gate + paper gate decide which may route live -> `build_feed` (broker ticks if streaming, else yfinance) -> `RunStore.create` -> `start_background_run` task in the module dict `_RUNS` -> hub `runs/started`. Stop: `stop_trading` -> `_cancel_local` or publish `runs:cancel` for the owning worker.
12. **Today page** (`routers/today.py::today`): each part wrapped by `part()` so one failure returns null plus `errors[name]`; `scoreboard` only for admins; also `phase`/`next_open` (`core/market_calendar.py`), `premarket` (phase `pre`) and `postclose` (`post`/`closed`) from `portfolio/digest.py::premarket_for`/`postclose_for`, `unjournaled` (`post` only; today's closed `mine` round trips with no note), `picks_top` (admin + `pre` only, `forecast/picks.py::rank_key` order); `_now()` is the test seam for the clock; `attention` returns `{count}` from `_needs_you` (admin flag passed, so data-quality items count for the admin).
13. **Admin status** (`GET /system/status` -> `system/status.py::cached_status`): gathers `deploy` (`GIT_SHA`, start time), `jobs` (incl. `data_alerts` = `data_quality.live`), `news`, `data`, `ai` blocks with `return_exceptions`, a failing block becomes `{error}`.

## Jobs and schedules

All times IST. Background loops start in `jobs.py::start_loops`, called by the `jobs` container (`python -m backend.jobs`) and, while `RUN_BACKGROUND_JOBS` is true (the default), by `startup_db_client` on every uvicorn worker (`--workers 2`, `backend/Dockerfile`). Set `RUN_BACKGROUND_JOBS=false` on `backend` once `jobs` runs. Cross-process safety comes from Redis locks inside each loop, so both running at once is safe. The `jobs` process beats `jobs:heartbeat` every 10 s (60 s TTL); `/health` reports its age as `jobs`.

| what | when | where | lock / guard |
|---|---|---|---|
| daily pass | 16:00 Mon-Fri (`RUN_HOUR`) | `scheduler.py::scheduler_loop` -> `_run_locked` -> `run_daily_jobs` | `scheduler:daily_lock` 2 h; skip if `scheduler:last_pass` >= day; then `_data_quality` -> `job:last:data_quality` (ok=0 when `failures`) |
| 09:20 catch-up of a missed pass | trading days | `engine/autorun.py` (other page) | same lock/last_pass |
| price + P&L pump | every 15 s | `ws/pump.py::pump_loop` | none (each worker serves its own sockets) |
| worker heartbeat | every 30 s (`ALIVE_TTL_SECONDS // 3`) | `runs.py::keep_alive` (API and jobs) | writes `worker:alive:<BOOT_ID>` |
| orphan sweep | once at startup | `RunStore.close_orphaned` | a RUNNING row whose boot id has no live key becomes STOPPED, `error="orphaned by restart"` |
| instrument expansion | startup, background | `server.py::_expand_instruments` | 20 h marker inside the loader |
| background loops | see the Jobs page | `jobs.py::start_loops`: scheduler, order sweeps, guardrail monitor (60 s, 9:15-15:35), autorun (60 s), Telegram poll, data-quality watch (300 s) | |
| ingest worker | separate container `neotrade-ingest` | `python -m backend.datalayer.worker` | Redis leader lock `ingest:leader` |

`system/jobs.py::LOOPS` = `guardrail_monitor, order_sweeps, autorun, telegram`; `DAILY_PASS`, `DATA_QUALITY`, `BUILDER` are the other `job:last:*` names the status panel reads.

## Invariants

- Every router except `auth`, `ws` and the root/health/docs routes is mounted with `get_current_user` (`server.py` include_router calls); nothing takes a user id from the URL or body: handlers use `user.id` (watchlist, profile, journal note ids are prefix-checked `routers/journal.py::set_round_trip_note`).
- Deployment-wide changes need `require_admin`: model, tiers, feature switches, Lab, portfolio-verdicts audience, gate backtests (`POST /trading/backtests/...`), builder run, backlog, system status, usage, picks, beta metrics. Role is re-derived from `ADMIN_EMAILS` on each login, so revoking needs an env edit plus re-login (`auth/store.py::_role_for`).
- Refresh tokens: only the SHA-256 is stored, rotation kills the old token, a replay beyond 10 s revokes the whole chain (`refresh_store.py::rotate`). The refresh cookie is path-scoped to `/api/v1/auth`.
- Broker credentials are refused rather than stored in plaintext when `CREDENTIAL_ENCRYPTION_KEY` is unset (`broker_credentials.py::save` raises `CredentialEncryptionUnavailable`; the route returns 503). `GET /settings/broker-credentials` returns only `configured` + masked key. Per-user Kite token key is scoped by user id (`kite_session.py::_redis_key`).
- Google ID tokens with `email_verified is False` are refused because the email decides admin (`auth/google.py:38`).
- Browsers cannot set WS headers, so the JWT rides `?token=`; the origin is checked by hand because CORS middleware does not cover WebSocket handshakes (`ws/routes.py` module docstring). `log_redaction.install()` (`server.py:50`) strips `token=` and `bot<id>:<secret>` from every handler and traceback.
- Events never cross users: `Hub.deliver` matches `message["user_id"]` and topic (`ws/hub.py:102`, tests `test_ws_hub.py`).
- A slow socket never stalls a publisher: queue is bounded (100), newest wins (`Connection.offer`).
- Live-order safety rails on the routes here: `approve-live` never trades the AI account, is refused when the kill switch tripped, outside 9:15-15:30 IST weekdays, over `per_trade_cap`, for a strategy that has not earned live (`for_mine`), and claims the suggestion as `SENDING` before the broker call (`routers/suggestions.py::place_live_approval`). It takes two calls: without `confirm_token` it only returns `NEEDS_SECOND_TAP` + a token bound to the suggestion's terms (`::_order_terms`); with it, `risk/live_confirm.py::redeem` spends the token (a refusal is `{detail, code}` from `TokenRefused.response()`: `confirm_expired|spent|mismatch` 409, `confirm_other_user` 403), then every rail runs (`::approve_suggestion_live`). `/orders/propose` only stores a confirm card; it runs on the user's `confirm` (second tap with the server's `confirm_token` for real money) at `/chat/actions/{id}/confirm` and cannot name the AI account or paper venue (`routers/orders.py`, `TicketRequest.venue: Literal["live"]`).
- `StartRequest` has no risk caps: sizing limits come from stored prefs, never the request (`trading.py::StartRequest`). A daily loss limit of 0 means off.
- Portfolio verdicts (SELL/HOLD/ADD) are admin-only unless `app_settings.portfolio_verdicts == "all"`; others see `REVIEW` and no plan (`routers/portfolio.py::mask_row`, `verdicts_visible_to`), pending SEBI RA registration (`PRODUCT.md`).
- Engine code uses `Clock`, never `datetime.now` (grep test `test_no_datetime_now.py`); compare `Side` by enum identity, not string (`core/models.py::Side` docstring: a past P0).
- Every per-account record carries `user_id` (CLAUDE.md invariant); `mine_book(user_id)` = `<uid>:mine`, autopilot book `<uid>:autopilot` keep real-money books apart from the AI paper book (`engine/persistence.py`).
- Rate limits fail open when Redis is down (`rate_limit.py::allow`); `mark` never raises (`system/jobs.py`).

## Endpoints

Generated from `app.routes` (FastAPI 0.141 `_IncludedRouter` walked for prefix and dependencies) at a51584a; 124 rows. Auth: `user` = bearer JWT via `get_current_user`; `admin` = also `require_admin` (403 otherwise); `none` = no bearer. Missing/invalid bearer returns 401/403 (HTTPBearer; the smoke test accepts either). `/api/v1/docs`, `/api/v1/redoc`, `/api/v1/openapi.json` are also public (Starlette routes, not in the table). Paths with `:path` take the rest including `:`.

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/google` | `backend/routers/auth.py::google_login` | none |
| POST | `/api/v1/auth/refresh` | `backend/routers/auth.py::refresh` | none |
| POST | `/api/v1/auth/logout` | `backend/routers/auth.py::logout` | none |
| GET | `/api/v1/auth/me` | `backend/routers/auth.py::get_me` | user |
| GET | `/api/v1/news/feed` | `backend/routers/news.py::news_feed` | user |
| GET | `/api/v1/news/symbols` | `backend/routers/news.py::symbol_news` | user |
| POST | `/api/v1/agents/quick-analyze/{symbol}` | `backend/routers/agents.py::quick_analyze_stock` | user |
| GET | `/api/v1/agents/intraday/{symbol}` | `backend/routers/agents.py::intraday_candles` | user |
| POST | `/api/v1/agents/analyze/{symbol}` | `backend/routers/agents.py::analyze_stock` | user |
| GET | `/api/v1/chat/actions/pending` | `backend/routers/chat_actions.py::pending_actions` | user |
| POST | `/api/v1/chat/actions/{action_id}/confirm` | `backend/routers/chat_actions.py::confirm_action` | user |
| POST | `/api/v1/chat/actions/{action_id}/cancel` | `backend/routers/chat_actions.py::cancel_action` | user |
| POST | `/api/v1/orders/propose` | `backend/routers/orders.py::propose` | user |
| GET | `/api/v1/settings/preferences` | `backend/routers/settings.py::get_preferences` | user |
| DELETE | `/api/v1/settings/goal` | `backend/routers/settings.py::remove_goal` | user |
| PUT | `/api/v1/settings/preferences` | `backend/routers/settings.py::update_preferences` | user |
| GET | `/api/v1/settings/autopilot/log` | `backend/routers/settings.py::autopilot_log` | user |
| GET | `/api/v1/settings/strategies` | `backend/routers/settings.py::list_strategies` | user |
| GET | `/api/v1/strategies/vocabulary` | `backend/routers/settings.py::strategy_vocabulary` | user |
| POST | `/api/v1/strategies/describe` | `backend/routers/settings.py::describe_strategy` | user |
| POST | `/api/v1/strategies/built` | `backend/routers/settings.py::submit_strategy` | user |
| POST | `/api/v1/strategies/built/{slug}/retire` | `backend/routers/settings.py::retire_strategy` | user |
| POST | `/api/v1/strategies/built/{slug}/retest` | `backend/routers/settings.py::retest_strategy` | user |
| GET | `/api/v1/strategies/built` | `backend/routers/settings.py::built_strategies` | user |
| GET | `/api/v1/strategies/library` | `backend/routers/settings.py::strategy_library` | user |
| GET | `/api/v1/settings/strategies/promotion` | `backend/routers/settings.py::strategy_promotion` | user |
| GET | `/api/v1/settings/portfolio-verdicts` | `backend/routers/settings.py::get_portfolio_verdicts` | admin |
| PUT | `/api/v1/settings/portfolio-verdicts` | `backend/routers/settings.py::set_portfolio_verdicts` | admin |
| GET | `/api/v1/settings/omniroute-models` | `backend/routers/settings.py::list_omniroute_models` | user |
| GET | `/api/v1/settings/omniroute-catalog` | `backend/routers/settings.py::omniroute_catalog` | user |
| GET | `/api/v1/settings/omniroute-model` | `backend/routers/settings.py::get_omniroute_model` | user |
| POST | `/api/v1/settings/omniroute-model` | `backend/routers/settings.py::set_omniroute_model` | admin |
| GET | `/api/v1/settings/omniroute-usage` | `backend/routers/settings.py::omniroute_usage` | admin |
| POST | `/api/v1/settings/omniroute-model/test` | `backend/routers/settings.py::test_omniroute_model` | admin |
| GET | `/api/v1/settings/omniroute-tiers` | `backend/routers/settings.py::get_omniroute_tiers` | user |
| POST | `/api/v1/settings/omniroute-tiers` | `backend/routers/settings.py::set_omniroute_tier` | admin |
| POST | `/api/v1/settings/llm-feature` | `backend/routers/settings.py::set_llm_feature` | admin |
| POST | `/api/v1/settings/lab` | `backend/routers/settings.py::set_lab` | admin |
| GET | `/api/v1/settings/broker-credentials` | `backend/routers/settings.py::get_broker_credentials` | user |
| POST | `/api/v1/settings/broker-credentials` | `backend/routers/settings.py::set_broker_credentials` | user |
| DELETE | `/api/v1/settings/broker-credentials` | `backend/routers/settings.py::delete_broker_credentials` | user |
| GET | `/api/v1/system/schedule` | `backend/system/router.py::system_schedule` | user |
| GET | `/api/v1/system/status` | `backend/system/router.py::system_status` | admin |
| POST | `/api/v1/system/builder/run` | `backend/system/router.py::run_builder` | admin |
| GET | `/api/v1/system/reconciliation?days=3` | `backend/system/router.py::reconciliation` | admin |
| GET | `/api/v1/system/backlog` | `backend/system/router.py::list_backlog` | admin |
| POST | `/api/v1/system/backlog` | `backend/system/router.py::create_backlog_item` | admin |
| PATCH | `/api/v1/system/backlog/{item_id}` | `backend/system/router.py::update_backlog_item` | admin |
| DELETE | `/api/v1/system/backlog/{item_id}` | `backend/system/router.py::delete_backlog_item` | admin |
| GET | `/api/v1/profile` | `backend/routers/profile.py::read_profile` | user |
| PUT | `/api/v1/profile` | `backend/routers/profile.py::update_profile` | user |
| POST | `/api/v1/profile/memories` | `backend/routers/profile.py::add_memory` | user |
| DELETE | `/api/v1/profile/memories/{memory_id}` | `backend/routers/profile.py::delete_memory` | user |
| GET | `/api/v1/today` | `backend/routers/today.py::today` | user |
| GET | `/api/v1/today/attention` | `backend/routers/today.py::attention` | user |
| GET | `/api/v1/today/reconciliation?days=7` | `backend/routers/today.py::reconciliation` | user |
| GET | `/api/v1/mine/history` | `backend/routers/mine.py::mine_history` | user |
| GET | `/api/v1/mine/overview` | `backend/routers/mine.py::overview` | user |
| GET | `/api/v1/mine/thesis/{symbol}` | `backend/routers/mine.py::get_thesis` | user |
| PUT | `/api/v1/mine/thesis/{symbol}` | `backend/routers/mine.py::put_thesis` | user |
| GET | `/api/v1/mine/tax` | `backend/routers/mine.py::tax` | user |
| GET | `/api/v1/mine/stock/{symbol}` | `backend/routers/mine.py::stock_detail` | user |
| GET | `/api/v1/mine/actions` | `backend/routers/mine.py::mine_actions` | user |
| POST | `/api/v1/mine/actions/{action_id:path}/dismiss` | `backend/routers/mine.py::dismiss_action` | user |
| POST | `/api/v1/mine/actions/{action_id:path}/snooze` | `backend/routers/mine.py::snooze_action` | user |
| GET | `/api/v1/mine/review/latest` | `backend/routers/mine.py::latest_review` | user |
| GET | `/api/v1/reports/weekly?week=` | `backend/routers/reports.py::weekly_report` | user |
| GET | `/api/v1/summaries/day` | `backend/routers/summaries.py::day` | user |
| GET | `/api/v1/summaries/holdings` | `backend/routers/summaries.py::holdings` | user |
| GET | `/api/v1/summaries/activity` | `backend/routers/summaries.py::activity` | user |
| GET | `/api/v1/summaries/weekly?week=` | `backend/routers/summaries.py::weekly` | user |
| GET | `/api/v1/summaries/habits` | `backend/routers/summaries.py::habits` | user |
| GET | `/api/v1/plan/today` | `backend/routers/plan.py::plan_today` | user |
| GET | `/api/v1/picks` | `backend/routers/picks.py::picks_today` | admin |
| GET | `/api/v1/picks/history` | `backend/routers/picks.py::picks_history` | admin |
| GET | `/api/v1/lab/runs?kind=&name=&limit=` | `backend/routers/lab.py::list_runs` (`lab_runs` newest first, `folds` omitted) | admin |
| GET | `/api/v1/lab/runs/{id}` | `backend/routers/lab.py::get_run` (full run, 404 if missing) | admin |
| GET | `/api/v1/forward/scorecard` | `backend/routers/forward.py::get_scorecard` (`{rows}` from `forward/scorecard.py::scorecard`) | admin |
| GET | `/api/v1/forward/records?source=&name=&limit=` | `backend/routers/forward.py::list_records` (`{records}`, newest first, `_id` returned as `id`) | admin |
| GET | `/api/v1/market/indices` | `backend/routers/market_data.py::get_market_indices` | user |
| GET | `/api/v1/market/trending` | `backend/routers/market_data.py::get_trending_stocks` | user |
| GET | `/api/v1/market/global` | `backend/routers/market_data.py::get_global_indices` | user |
| GET | `/api/v1/market/index/{ticker}` | `backend/routers/market_data.py::get_index_detail` | user |
| GET | `/api/v1/market/index/{ticker}/analysis` | `backend/routers/market_data.py::get_index_analysis` | user |
| GET | `/api/v1/market/brief` | `backend/routers/market_data.py::get_market_brief` (stored, no model call; 404 if none) | user |
| GET | `/api/v1/research/{symbol}/note` | `backend/routers/market_data.py::get_cached_note` (cached analyst note, no model call; 404 if none) | user |
| GET | `/api/v1/market/scan` | `backend/routers/market_data.py::get_market_scan` (`market_scan` over `news_sources.universe_rows` + `_cached_quotes` + a 365-day `daily_bars` high/low aggregate; `{gainers,losers,near_high,near_low (2%),sectors[{sector,change_pct,up,n}],breadth{up,down,n},at}`; market_cache `scan` 5 min) | user |
| GET | `/api/v1/market/quotes` | `backend/routers/market_data.py::get_quotes` (<= 8 symbols; ingest `quote:` cache first via `_cached_quotes`, Yahoo for misses; rows `{symbol,price,change_pct,at}`) | user |
| GET | `/api/v1/options/expiries` | `backend/routers/options.py::get_expiries` | user |
| GET | `/api/v1/options/chain` | `backend/routers/options.py::get_chain` | user |
| GET | `/api/v1/watchlist` | `backend/routers/watchlist.py::get_watchlist` | user |
| POST | `/api/v1/watchlist/add` | `backend/routers/watchlist.py::add_to_watchlist` | user |
| DELETE | `/api/v1/watchlist/remove/{symbol}` | `backend/routers/watchlist.py::remove_from_watchlist` | user |
| GET | `/api/v1/watchlist/details` | `backend/routers/watchlist.py::get_watchlist_details` (price/day change/`at` from `market_data._cached_quotes`, names from `instruments`; Yahoo `fetch_stock_info_logic` only for a miss) | user |
| POST | `/api/v1/trading/start` | `backend/routers/trading.py::start_trading` | user |
| POST | `/api/v1/trading/stop` | `backend/routers/trading.py::stop_trading` | user |
| GET | `/api/v1/trading/runs` | `backend/routers/trading.py::list_runs` | user |
| GET | `/api/v1/trading/positions` | `backend/routers/trading.py::get_positions` | user |
| GET | `/api/v1/trading/kill-switch` | `backend/routers/trading.py::get_kill_switch` | user |
| GET | `/api/v1/trading/fills` | `backend/routers/trading.py::get_fills` | user |
| GET | `/api/v1/trading/trades` | `backend/routers/trading.py::get_trades` | user |
| GET | `/api/v1/trading/equity` | `backend/routers/trading.py::get_equity` | user |
| GET | `/api/v1/trading/instruments` | `backend/routers/trading.py::search_instruments` | user |
| POST | `/api/v1/trading/backtests/{strategy_name}` | `backend/routers/trading.py::run_gate_backtest` | admin |
| GET | `/api/v1/trading/backtests/{strategy_name}` | `backend/routers/trading.py::latest_gate_backtest` | user |
| POST | `/api/v1/suggestions/scan` | `backend/routers/suggestions.py::scan_now` | user |
| GET | `/api/v1/suggestions` | `backend/routers/suggestions.py::list_suggestions` | user |
| POST | `/api/v1/suggestions/{suggestion_id}/reject` | `backend/routers/suggestions.py::reject_suggestion` | user |
| POST | `/api/v1/suggestions/{suggestion_id}/approve-live` | `backend/routers/suggestions.py::approve_suggestion_live` | user |
| GET | `/api/v1/analytics/pnl` | `backend/routers/analytics.py::get_pnl` | user |
| GET | `/api/v1/analytics/scorecard` | `backend/routers/analytics.py::get_scorecard` | user |
| GET | `/api/v1/broker/list` | `backend/routers/broker.py::list_brokers` | user |
| GET | `/api/v1/broker/{broker}/status` | `backend/routers/broker.py::broker_status` | user |
| GET | `/api/v1/broker/{broker}/login-url` | `backend/routers/broker.py::broker_login_url` | user |
| POST | `/api/v1/broker/{broker}/connect` | `backend/routers/broker.py::broker_connect` | user |
| POST | `/api/v1/broker/{broker}/disconnect` | `backend/routers/broker.py::broker_disconnect` | user |
| GET | `/api/v1/journal` | `backend/routers/journal.py::get_journal` | user |
| GET | `/api/v1/journal/ai-vs-me` | `backend/routers/journal.py::ai_vs_me` | user |
| POST | `/api/v1/journal/sync` | `backend/routers/journal.py::sync_journal` | user |
| POST | `/api/v1/imports/cas` | `backend/routers/imports.py::import_cas` | user |
| GET | `/api/v1/imports` | `backend/routers/imports.py::imported` | user |
| DELETE | `/api/v1/imports` | `backend/routers/imports.py::delete_imported` | user |
| POST | `/api/v1/journal/import/zerodha-console` | `backend/routers/journal.py::import_console_csv` | user |
| POST | `/api/v1/journal/import/upstox-history` | `backend/routers/journal.py::import_upstox` | user |
| PUT | `/api/v1/journal/round-trips/{round_trip_id}/note` | `backend/routers/journal.py::set_round_trip_note` | user |
| GET | `/api/v1/journal/learning` | `backend/routers/journal.py::get_learning` | user |
| GET | `/api/v1/journal/beta-metrics` | `backend/routers/journal.py::get_beta_metrics` | admin |
| GET | `/api/v1/guardrails` | `backend/routers/guardrails.py::guardrail_status` | user |
| PUT | `/api/v1/guardrails/telegram/bot` | `backend/routers/guardrails.py::telegram_set_bot` | user |
| DELETE | `/api/v1/guardrails/telegram/bot` | `backend/routers/guardrails.py::telegram_remove_bot` | user |
| POST | `/api/v1/guardrails/telegram/link` | `backend/routers/guardrails.py::telegram_link` | user |
| POST | `/api/v1/guardrails/telegram/verify` | `backend/routers/guardrails.py::telegram_verify` | user |
| DELETE | `/api/v1/guardrails/telegram` | `backend/routers/guardrails.py::telegram_unlink` | user |
| GET | `/api/v1/portfolio` | `backend/routers/portfolio.py::get_portfolio` | user |
| POST | `/api/v1/portfolio/refresh` | `backend/routers/portfolio.py::refresh` | user |
| GET | `/api/v1/portfolio/rebalance/candidates` | `backend/routers/portfolio.py::rebalance_candidates` | user |
| POST | `/api/v1/portfolio/rebalance` | `backend/routers/portfolio.py::rebalance` | user |
| WS | `/api/v1/ws` | `backend/ws/routes.py::stream` | none |
| GET | `/docs` | `backend/server.py::redirect_docs` | none |
| GET | `/redoc` | `backend/server.py::redirect_redoc` | none |
| GET,HEAD | `/` | `backend/server.py::root` | none |
| GET | `/health` | `backend/server.py::health` | none |

Response keys (from handler code):

- `POST /auth/google` `{token, user{id,google_sub,email,name,picture,created_at,role}}`; `/auth/refresh` `{token}`; `/auth/logout` `{message}`; `/auth/me` the `User`.
- `GET /today` `market{open,as_of}`, `phase`, `next_open`, `premarket`, `postclose`, `unjournaled`, `picks_top[{symbol,label,median}]` (grade A only), `accounts`, `live_armed{autopilot,strategies}`, `kill_switch`, `pulse`, `needs_you[]`, `mine_actions` (top 3), `mine_actions_total`, `scoreboard` (admin), `proposals_total`, `ai_activity`, `autopilot{enabled,live,capital=account_size,exposure_cap=max_exposure,deployed}`, `setup{done,total,steps}`, `backdrop`, `errors`. `GET /today/attention` `{count}`.
- `GET /analytics/pnl` `today{realized,unrealized,trades,wins,losses,turnover,costs,net}`, `month{...,win_rate,best,worst}`, `all_time`, `open{positions,exposure,equity}` (`analytics.py::compute_pnl`); the `pnl/updated` socket event has the same keys plus `paper` and `live{mine,ai}`. `?venue=live` returns `{mine:<pnl>, ai:<pnl>}` (not the flat shape): the real-money books are separate, never summed. `GET /analytics/scorecard` `venue, account_size, days, strategies, totals, nifty_return_pct`.
- `GET /trading/runs` list of run docs; `POST /trading/start` `{run_id}`; `POST /trading/stop` `{run_id, stopped}`; `GET /trading/kill-switch` `{tripped, reason?, equity?, tripped_at?}`; `GET /trading/positions` symbol -> position dict.
- `GET /system/status` `{as_of, deploy, jobs, news, data, ai}` (each may be `{error}`); `GET /health` `{api:"ok", ingest}`.
- `GET /settings/preferences` the merged `DEFAULTS`+stored; `GET /settings/omniroute-tiers` `{tiers, fallback, features_off}`; `GET /settings/omniroute-usage` `{key_name, tokens, cost, providers, as_of, refreshing?}`.
- `POST /suggestions/scan` 202 `{started, symbols}`; `POST /suggestions/{id}/approve-live` the settled suggestion; `POST /orders/propose` the stored chat action card.
- `GET /picks` `{date, shown (served, max 3 per grade A/B/C), hidden_count, hidden_reason, grades, grade_text, picks (all candidates), setups, as_of, forward, caveats}`; `GET /plan/today` `{plan, versions, scorecards, weeks_beating}`; `GET /options/chain` `{underlying,name,expiry,spot,atm_strike,pcr,strikes}`.

## Deploy

Two supported paths, chosen once per session (host `/home/ubuntu/CLAUDE.md`, "Deploy mode"); the repo default is CI/CD.

- **CI/CD (default).** Push to `main`. `.github/workflows/ci.yml` (`CI`): path filter, then backend job (`pytest -q` from repo root per `pytest.ini` `testpaths = backend/tests`, then `docker build ./backend`) and frontend job (`npm ci`, `lint`, `build`, Node 22). On CI success for a push, `deploy-backend.yml` (`workflow_run`, also `workflow_dispatch` with `force`) calls `kushgarg132/ci-workflows/.github/workflows/deploy-backend.yml@main` on the self-hosted runner label `neotrade`: updates the deploy clone `/home/ubuntu/deploys/NeoTrade` (real `.env`, gitignored), skips unless `backend/**` or `docker-compose.yml` changed (or `force`), runs `docker compose up -d --build backend` with `GIT_SHA` exported (also rebuilds `ingest`, via `depends_on`), health-checks `http://127.0.0.1:8000/` and container `neotrade-backend`. Verify with `gh run watch <id> --exit-status` plus a health check; do not also build by hand. Vercel builds the frontend (root `frontend/`) from the same push.
- **Direct.** End the HEAD commit subject with `[skip ci]` and push (no workflow runs, no deploy). Then in `/home/ubuntu/deploys/NeoTrade`: `git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend`. Vercel still auto-builds the frontend (it ignores `[skip ci]`); do not run `vercel deploy`.
- Container: image `python:3.11-slim`, `CMD uvicorn backend.server:app --port 8000 --workers 2`, `GIT_SHA` baked as env (shown in `/system/status` `deploy.backend_sha`). Compose publishes `127.0.0.1:${BACKEND_PORT:-8000}:8000`; Nginx + Let's Encrypt on the VM fronts `https://neotrade.161.118.167.148.nip.io`. Mongo (Atlas) and Redis (Upstash) are remote, no containers. Services: `backend`, `ingest`, `jobs` (same image, no port; `backend` `depends_on` both).
- One-time: `docker exec neotrade-backend python -m backend.system.seed_backlog`.
- Env var NAMES read by the backend (`configs/settings.py::Settings`; compose passes the first group through `environment`): `MONGODB_URL`, `DATABASE_NAME`, `REDIS_URL`, `OMNIROUTE_API_KEY`, `OMNIROUTE_FEATURE_KEYS`, `FINNHUB_API_KEY`, `GOOGLE_CLIENT_ID`, `JWT_SECRET`, `CORS_ALLOWED_ORIGINS`, `CREDENTIAL_ENCRYPTION_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_EMAILS`, `GIT_SHA`, `BACKEND_PORT` (compose-only). Settings with defaults not in compose (set only if the `.env` is read some other way): `OMNIROUTE_API_KEYS`, `OMNIROUTE_BASE_URL`, `OMNIROUTE_MODEL`, `NEWS_LLM_CALLS_PER_DAY` (200), `USER_LLM_CALLS_PER_DAY` (150), `PLAN_LLM_CALLS_PER_DAY` (100), `AI_TOOLS_ENABLED`, `SESSION_MAX_AGE_SECONDS` (1800), `REFRESH_TOKEN_MAX_AGE_SECONDS`, `REFRESH_COOKIE_NAME`, `PROJECT_NAME`, `VERSION`, `API_PREFIX`, `SERVER_PORT`, `LOG_LEVEL`. `ADMIN_EMAILS` and `CORS_ALLOWED_ORIGINS` are comma-separated; `OMNIROUTE_FEATURE_KEYS` is a JSON object.

## Import rules

`backend/.importlinter` (run `lint-imports --config backend/.importlinter` from the repo root or `/app`): domain modules (incl. `backend.forward`) never import `backend.routers`; `backend.mine` and `backend.journal` never import `backend.autopilot`; nothing imports `backend.forecast.research`; `backend.lab` never imports `backend.routers` or `backend.autopilot`; `backend.ml` and `backend.rl` never import `backend.routers`, `backend.autopilot` or `backend.engine`, and the app (ai, autopilot, engine, forecast, lab, mine, plan, portfolio, routers, scheduler, server, jobs, system; `backend.ml` too for `backend.rl`) never imports `backend.ml` or `backend.rl`. Only direct imports are checked (`allow_indirect_imports`); 14 existing domain-to-router imports sit under `ignore_imports` as known debt, removed when fixed.

## Gotchas and known issues

- **`JWT_SECRET` is checked at startup.** `settings.py::require_jwt_secret` (called first in `server.py::startup_db_client`) raises when it is empty (compose passes `${JWT_SECRET:-}`) or the public default, unless `ALLOW_INSECURE_JWT_SECRET=true` (dev only; tests never run startup so they are unaffected).
- **`broadcast.listen_forever`** (what `server.py` starts) re-runs `listen` every `RECONNECT_SECONDS` after a Redis drop; plain `listen` still returns when its stream ends.
- **Live P&L is two books.** Live fills land in `<uid>:mine` (own account) and `<uid>:autopilot` (AI account live); `analytics.py::compute_live_pnl` reads each, used by `/analytics/pnl?venue=live` and `ws/pump.py::push_once`. `/trading/*?venue=live` still reads only `<uid>:mine`.
- `POST /trading/stop` 404s unless the run is owned and still `RUNNING` (`trading.py::stop_trading`), so a stopped run is not re-published.
- Watchlist: unique `user_id` index (`server.py::ensure_collection_indexes`) and `_load_or_create` upserts; `POST /watchlist/add?symbol=` validates the shape (<=30 chars, `[A-Za-z0-9&._ -]`) but not that the instrument exists.
- `PreferencesPatch` bounds `daily_loss_limit` (>=0), the guardrail ints, and `account_size`, `max_exposure`, `per_trade_cap` (>0, finite).
- A socket authenticates at the handshake and `ws/routes.py::_close_at_expiry` closes it (1008) when the JWT `exp` passes, so the client reconnects with a refreshed token. It is not re-checked against user deletion.
- HTTP `POST /agents/quick-analyze/{symbol}` shares the socket's `quick_analyze:<uid>` budget (60/min); HTTP `analyze` has 10/min. `/market/index/{ticker}/analysis` is Redis-cached per index (`research/index_move.py`), so it is not an LLM-cost path per user.
- `locks.py` is only used by the ingest worker; `trading.py:305` and `scheduler.py:232` release their locks with their own get-then-delete (not atomic, fine while TTL >> hold).
- `KiteSessionManager` error strings still say `KITE_API_KEY` (`kite_session.py:100,109`) though keys are per-user now (cosmetic).
- Handbook drift: `frontend/src/handbook/jobs-and-ops.md` says the heartbeat is ~10 s (code: 30 s) and that `/health` reports Mongo/Redis (code returns only `{api, ingest}`, `server.py:304`). Deploy health check hits `/`, not `/health`.
- `lab_on` logs once per day using `date.today()` (container local date, UTC), not IST (`app_settings.py:62`); only log timing.
- `AppSettingsStore.set_portfolio_verdicts` does no value check; only the route's `Literal["admin","all"]` guards it.
- Mongo datetimes: `tz_aware=True` on the client, but older code still has naive-UTC fixes (`_aware`, `_as_utc`); a naive datetime sent to the browser is read as IST.
- Past fixes in this area: `69b7e93` refuse unverified Google email; `64e5224` / `1d970b4` log redaction keeps args shape and covers non-string messages; `8b3c906` LLM limits on HTTP analyze, verdict gate in chat; `def98ec` bot tokens redacted from logs; `86938d2` loss limit 0 = off and restarts keep the day's realized loss; `9af6ed6` Lab switch gates experimental AI jobs (default off); `4842262` Picks admin-only; `22a645b` Today scoreboard "You vs Picks".

## Tests

| file | covers |
|---|---|
| `test_auth_jwt.py`, `test_auth_google.py`, `test_auth_store.py`, `test_auth_dependency.py`, `test_auth_router.py` | session JWT, Google verify, user upsert/role, bearer + admin dependency, login/me |
| `test_refresh_tokens.py`, `test_auth_refresh_router.py` | rotation, replay revocation, grace window, cookie attributes, logout |
| `test_routes_require_auth.py` | one sample path per router rejects no-bearer (not an exhaustive map; admin routes not checked) |
| `test_broker_credentials_store.py`, `test_kite_session*.py`, `test_broker_router.py`, `test_settings_router.py` | encryption, Kite token lifecycle, connect flow, settings/credentials/usage/strategies routes |
| `test_settings.py`, `test_app_settings.py` | env parsing (keys, CORS, admin emails), app_settings cache/tiers/features/Lab |
| `test_ws_hub.py`, `test_ws_routes.py`, `test_ws_pump.py`, `test_broadcast.py` | fan-out, user isolation, origin/token refusal, actions + budgets, pump, bus fallback |
| `test_log_redaction.py` | token and bot-token redaction, uvicorn args shape |
| `test_rate_limit.py`, `test_trading_router.py`, `test_run_restart.py`, `test_ledger_scoping.py` | limiter, run start/stop and lock, per-user ledger scoping |
| `test_system_status.py`, `test_system_jobs.py`, `test_system_backlog.py`, `test_data_quality.py` | status blocks + cache + admin gate, job marks, backlog CRUD, data-quality check |
| `test_profile_router.py`, `test_profile_store.py` | profile + memories |
| `test_analytics.py`, `test_marks.py` | P&L/scorecard maths, mark prices |
| `test_today.py`, `test_mine_router.py`, `test_plan_router.py`, `test_orders_router.py`, `test_suggestions_router.py`, `test_portfolio_rebalance_router.py`, `test_market_quotes.py`, `test_market_index_detail.py`, `test_option_chain.py` | the matching routers |
| `test_core_models.py`, `test_no_datetime_now.py` | engine types, no direct `datetime.now` in core/engine |
| none | `routers/watchlist.py`, `routers/agents.py`, `routers/guardrails.py` handlers other than `telegram_set_bot` (a rejected token is a 400, `test_telegram_transport.py`), `routers/picks.py` (only auth smoke / forecast tests) |
