# System & Data

How the pieces are deployed, where every number comes from, and where it is kept.
Anchors are `file::symbol`; when this and the code disagree, the code is right and
this file is the bug — fix it in the same commit.

## System map

| Piece | Where it runs | Notes |
|---|---|---|
| Frontend | Vercel project `neotrade`, root `frontend/`, `https://neotrade-trading.vercel.app` | React 19 + Vite, installs to the home screen. One WebSocket for live figures, REST for everything else. Builds on every push to `main` (Vercel ignores `[skip ci]`). |
| TLS + proxy | Nginx on the Oracle VM, Let's Encrypt cert for `neotrade.161.118.167.148.nip.io` → `127.0.0.1:8000` | `access_log … notoken` keeps `?token=` out of the access log. |
| API | Container `neotrade-backend`, `uvicorn backend.server:app --workers 2` | Routers, the trading engine, every in-process loop (Jobs & Ops). |
| Ingest worker | Container `neotrade-ingest`, `python -m backend.datalayer.worker` | Same image, no port. Prices, macro, news, bars, plan revisions. One leader at a time. |
| Database | MongoDB Atlas (managed) | The book of record. |
| Cache / bus | Upstash Redis (managed) | Broker tokens, quotes, sentiment, locks, cross-worker pub/sub, job records. |
| LLM gateway | OmniRoute container `omniroute` on the same VM, `http://omniroute:20128/v1` | The only door to models. See AI & News. |
| Brokers | Kite, Upstox, Angel One — per user | Holdings, trades, positions, orders, option chains. |

<!-- live:deploy -->

## Multi-worker

Two uvicorn workers serve the API, so nothing important lives in one process:

- WebSocket fan-out goes through Redis pub/sub (`backend/broadcast.py`, published from `backend/ws/publish.py`), so a socket on
  worker A sees an event raised on worker B.
- Each worker writes `worker:alive:<boot id>` every few seconds (`backend/runs.py`); a run
  whose worker stopped beating is marked orphaned, not left RUNNING.
- The daily pass takes `scheduler:daily_lock` and records `scheduler:last_pass`, so it runs once.
- Each worker keeps its own small caches (gateway usage, status, quote reads); they are
  per-process on purpose and short-lived.

## Brokers

Every broker sits behind `BrokerAdapter` (`backend/brokers/protocol.py`), chosen per user by
`backend/brokers/registry.py::get_broker_adapter` and built from that user's own
Fernet-encrypted credentials (`broker_credentials`), never from process settings. Access
tokens are cached as `broker:<user_id>:<broker>:access_token`.

| Capability | Kite | Upstox | Angel One |
|---|---|---|---|
| Login | redirect + request token | OAuth code | client code + password + 6-digit TOTP |
| Market data / history | yes (a year of 5-min via 99-day windows) | yes | yes |
| Live stream | `KiteTickerFeed`, only if the app has the market-data add-on (`KiteAdapter::ticker_feed` probes `ltp`; refused → next broker) | `UpstoxMarketFeed` (v3 protobuf) | none — falls back to polling |
| Holdings | stocks + mutual funds | long-term holdings | `getHolding` |
| Trade history import | via journal sync / Console CSV | API, a year in month windows | — |
| Equity orders | yes | yes | yes |
| Option orders | yes (NFO) | yes (matched on its chain) | refused (`supports_options`) |
| Option chain | — | NIFTY / BANK NIFTY | — |

Roles (`backend/brokers/roles.py`, `prefs.broker_roles`): each connected broker is `mine`
(your own account) or `ai` (at most one — the autopilot's). Orders route by role and never
fall back to another account.

## Market data, best source first

| Need | Source | Fallback |
|---|---|---|
| Live quotes | Redis `quote:<SYM>` written by ingest `quotes` (held + watched every ~15 s in session, Nifty 200 every 5 min) | yfinance fetch, written back |
| Prices that place real orders | always fetched live at confirm time (`routers/suggestions._live_mark_price`, `chat/actions._mark_price`) | none — no guessed price |
| Intraday bars for a run | broker stream (Kite / Upstox) | `CandlePollingFeed`: yfinance 5-min candles, ~15 min late |
| Daily bars | Mongo `daily_bars` (ingest `bars`, after 3:45 PM IST; Nifty 200, scan lists, held, watched; 10 years of `^NSEI`). Stocks from the admin's Upstox/Kite session when up (Yahoo misdates some splits), Yahoo for the rest | yfinance for intraday intervals, uncovered symbols, stale (> 4 days) or longer periods |
| Fundamentals | `fundamentals` collection (ingest daily) | yfinance |
| Indices, crude, gold, FX, US 10Y | Redis `macro:<ticker>` (ingest `macro`, 60 s) + `macro_series` | yfinance |
| FII / DII flows | NSE, ingest `flows` (30 min) → `market:flows` | — |
| Econ calendar | ForexFactory weekly feed → `econ_calendar` (6 h) | — (no RBI dates) |
| Option premiums | Kite quote of the contract, else the Upstox chain | Black-Scholes, flagged `premium_is_live: false` |
| Instruments | `instruments` from Kite's dump on connect plus free NSE/BSE lists | — |

The store holds completed bars only, so during the session the newest daily bar is yesterday's.

## Where data lives

**Mongo — per user** (every document carries `user_id`):
`paper_orders`, `paper_fills`, `paper_positions`, `paper_trades`, `paper_limit_orders`,
`live_orders`, `suggestions`, `user_prefs`, `trading_runs`, `watchlist`, `journal_trades`,
`journal_notes`, `journal_opens`, `portfolio_snapshots`, `guardrail_events`, `chat_actions`,
`user_profiles`, `trade_plans`, `learning_state`, `learning_changes`, `factor_books`,
`broker_credentials` (encrypted), `alert_channels` (encrypted bot tokens), `refresh_tokens` (hashed).

**Mongo — shared reference data:** `users`, `instruments`, `instrument_meta`,
`instrument_sectors`, `daily_bars`, `fundamentals`, `stock_health`, `macro_series`,
`econ_calendar`, `news_items`, `news_outcomes`, `strategy_backtests`,
`strategy_retunes`, `strategy_hypotheses`, `retune_runs`, `app_settings`,
`backlog` (the Future page).

**Redis key families:**

| Prefix | What |
|---|---|
| `broker:<user>:<broker>:access_token` | broker sessions |
| `quote:`, `macro:`, `bars:` | price caches from ingest |
| `sentiment:<SYM>`, `sector_sentiment:`, `market:sentiment`, `analyst_verdict:<SYM>` | news-derived scores |
| `market:regime`, `market:brief`, `market:flows` | the backdrop |
| `news:deep_calls:<day>`, `plan:calls:<day>` | daily AI budgets |
| `news:alerted:…`, `news:scanned:…` | once-per-window guards |
| `plan:<user>:<date>` | today's game plan |
| `ingest:heartbeat:<loop>`, `ingest:leader` | ingest health and leadership |
| `worker:alive:<boot>` | API worker liveness |
| `scheduler:daily_lock`, `scheduler:last_pass` | the daily pass |
| `autorun:<user>` | which worker owns a user's auto run |
| `job:last:<name>` | each job's last run (the Jobs panel) |
| `telegram:…` | bot polling lock and chat history |

<!-- live:data -->
