---
page: mine-portfolio-journal
covers: [backend/mine/**, backend/portfolio/**, backend/journal/**, backend/guardrails/**, backend/routers/mine.py, backend/routers/portfolio.py, backend/routers/journal.py, backend/routers/today.py, backend/routers/imports.py]
verified_at: c0b6f85
---
# Mine, Portfolio, Journal, Guardrails and Today

This page covers the user's own (`mine`-role) broker account end to end. That includes the journal of real broker
executions (round trips, insights, charge mirrors), the daily holdings review (scorecard, rule verdicts, AI write-up,
rebalance), and the Mine pages (value curve and XIRR, Needs-you list, FIFO tax lots, thesis, corporate events). It
also covers guardrails (per-minute limit checks, kill-switch trip, MIS square-off), Telegram alerts and the inbound
bot, and `GET /today`, which assembles all of these. Every collection is keyed by `user_id`. Account scoping
always goes through `backend/brokers/roles.py::brokers_for(roles, "mine")`. An empty set means "no roles set". Most
callers then treat every broker as mine (`mine or None` / `if mine`).

## Files

| path | role | key symbols |
|---|---|---|
| backend/mine/actions.py | Builds the ranked "Needs you" list, handles dismiss and snooze, and sends stop/target alerts | `mine/actions.py::RANK`, `::build`, `::ideas`, `::_levels`, `::dismiss`, `::snooze`, `::level_alerts`, `::levels_text` |
| backend/mine/events.py | Results and ex-dividend dates from yfinance, plus dividends received | `events.py::refresh`, `::loop`, `::upcoming`, `::dividends_received`, `::_fetch_sync` |
| backend/mine/history.py | Daily value curve `mine_daily`, replayed from journal trades; XIRR | `history.py::xirr`, `::_inputs`, `::_compute`, `::_store`, `::backfill`, `::write_all`, `::series`, `::returns` |
| backend/mine/lots.py | FIFO lots, realised matches, broker reconciliation, split detection | `lots.py::_fifo`, `::open_lots`, `::realised`, `::unmatched`, `::split_ratio`, `::reconcile`, `::mine_trades` |
| backend/routers/mine.py (`GET /mine/review/latest`) | The latest non-empty AI portfolio `summary` on the user's `portfolio_snapshots` as `{text, date}` (IST day); no LLM; 404 until one exists | `mine.py::latest_review` |
| backend/mine/stock.py | One-stock detail page | `stock.py::detail`, `::_verdicts`, `::_news` |
| backend/mine/tax.py | Indian FY capital-gains estimate (pure) | `tax.py::report`, `::est_tax`, `::long_from`, `::is_long`, `::current_fy`, `STCG_RATE`, `LTCG_RATE`, `LTCG_EXEMPTION` |
| backend/mine/thesis.py | User's why/target/stop/review_by per holding | `thesis.py::ThesisIn`, `::ThesisStore`, `SYMBOL` |
| backend/portfolio/service.py | Fetches holdings, builds the scorecard, runs the review, stores snapshots, reprices from live quotes | `portfolio/service.py::refresh_portfolio`, `::fetch_holdings`, `::_review`, `::daily_reviews`, `::with_live_prices`, `::quoted`, `::scorecard_for`, `::mine_holdings`, `::mine_avg_prices`, `::latest_snapshot`, `::add_candidates`, `::_nifty`, `::_sectors`, `::_closes` |
| backend/portfolio/scorecard.py | Merges holdings by ISIN; totals, NIFTY benchmark, concentration (pure) | `scorecard.py::merge`, `::build_scorecard`, `::correlated_pairs` |
| backend/portfolio/rules.py | SELL/HOLD/ADD and REVIEW/KEEP rules, scored through composite (pure) | `portfolio/rules.py::stock_verdict`, `::fund_verdict`, `::sell_codes`, `::add_codes`, `::worsened`, `SEVERITY` |
| backend/portfolio/health.py | Per-stock fundamentals, trend and headlines, cached daily | `health.py::stock_health`, `::price_trend`, `::profit_trend` |
| backend/portfolio/review.py | LLM write-up (summary, notes, plan); explains only | `review.py::write_review`, `MAX_HOLDINGS` |
| backend/portfolio/rebalance.py | Target weights, rebalance plan, one-tap suggestion, charges, sell tax | `rebalance.py::target_weights`, `::target_gaps`, `::plan_rebalance`, `::suggest`, `::charges`, `::sell_tax`, `::multiplier`, `DEFAULT_TARGETS` |
| backend/portfolio/digest.py | Pulse (account right now), scoreboard, 08:45 and post-close Telegram digests | `digest.py::pulse`, `::verdicts_visible`, `::headlines_for`, `::pnl_since`, `::scoreboard`, `::send_premarket`, `::send_postclose`, `::premarket_for`, `::postclose_for` (per-user bodies, shared with `/today`), `::premarket_text`, `::postclose_text`, `::last_session_move` |
| backend/journal/store.py | `journal_trades` / `journal_notes` persistence | `journal/store.py::JournalStore.add_trades`, `.list_trades`, `.notes_for`, `.set_note` |
| backend/journal/roundtrips.py | Groups fills into round trips; instrument kind (pure) | `roundtrips.py::build_round_trips`, `::daily_pnl`, `::instrument_kind`, `::underlying_of` |
| backend/journal/sync.py | Pulls today's trade book from ACTIVE brokers; Upstox history backfill | `sync.py::sync_user_trades`, `::import_upstox_history`, `::connected_brokers` |
| backend/journal/console_csv.py | Parses the Zerodha Console tradebook CSV | `console_csv.py::parse_console_tradebook` |
| backend/journal/mirror.py | Estimated charges, trade frequency, return vs NIFTY | `mirror.py::costs`, `::benchmark`, `::text` |
| backend/journal/insights.py | Behaviour findings over closed trips (pure) | `insights.py::build_insights`, `MIN_TRIPS` |
| backend/journal/news.py | Attaches the strongest news impact in the 24h before each trip opened | `news.py::attach_news` |
| backend/journal/accounts.py | Splits by account; monthly AI-vs-me | `accounts.py::filter_trades`, `::brokers_of`, `::ai_vs_me` |
| backend/journal/beta.py | `journal_opens` tracking; Phase 12 metrics | `beta.py::record_open`, `::beta_metrics` |
| backend/guardrails/rules.py | Breach evaluation (pure) | `guardrails/rules.py::evaluate`, `::_option_breaches`, `::_is_hedged` |
| backend/guardrails/monitor.py | 60s in-session loop; kill-switch trip; square-off | `guardrails/monitor.py::run_tick`, `::check_user`, `::square_off`, `::monitor_loop`, `::start`, `LOCK_KEY` |
| backend/guardrails/square_off.py | Position book to MIS exit orders (pure) | `guardrails/square_off.py::exit_orders`, `::describe` |
| backend/guardrails/store.py | Breach dedupe; alert channel and encrypted user bot token | `guardrails/store.py::GuardrailStore.record`, `.events_for`, `.telegram_channel`, `.telegram_routes`, `.set_telegram_bot` |
| backend/guardrails/telegram.py | Bot API client over aiogram 3.31 (one `Bot` per token per event loop; dicts in and out): send, HTML, drafts, `alert` | `telegram.py::alert`, `::_bot`, `::_call`, `::send`, `::send_html`, `::to_html`, `::find_chat`, `::updates` |
| backend/guardrails/telegram_bot.py | Inbound long-poll bridge to the chat agent and action cards | `telegram_bot.py::poll_loop`, `::poll_once`, `::_poll_bot`, `::_reply`, `::_callback`, `::_ask`, `::Tap`, `SHORTCUTS` |
| backend/routers/mine.py | `/mine/*` | `mine.py::overview`, `::mine_history`, `::tax`, `::stock_detail`, `::get_thesis`, `::put_thesis`, `::mine_actions`, `::dismiss_action`, `::snooze_action`, `::_month_contributions`, `TAX_FIRST_FY` |
| backend/routers/portfolio.py | `/portfolio*`; verdict masking | `portfolio.py::get_portfolio`, `::refresh`, `::rebalance`, `::rebalance_candidates`, `::present`, `::mask_row`, `::verdicts_visible_to`, `::with_suggestions`, `::_candidate_symbols` |
| backend/routers/journal.py | `/journal*` | `journal.py::get_journal`, `::sync_journal`, `::import_console_csv`, `::import_upstox`, `::set_round_trip_note`, `::ai_vs_me`, `::get_learning`, `::get_beta_metrics` |
| backend/routers/today.py | `/today`, `/today/attention`, `/today/reconciliation` | `today.py::today`, `::attention`, `::reconciliation`, `::_accounts`, `::_needs_you`, `::_mine_actions`, `::_setup`, `::_autopilot`, `::_backdrop`, `_STATE_CACHE` |

## Data

**Mongo**
- `mf_imports` (`_id = user_id`: `holdings[]` as `Holding` dicts with `kind=MF, broker="cas", symbol=isin`, `period`, `imported_at`) and `mf_transactions` (`_id = "{user}:{n}"`: folio, isin, scheme, date, type, units, nav, amount): a CAMS/KFintech CAS PDF parsed by casparser in memory (`mine/cas_import.py::parse_cas`, `::from_cas`, `::save`); the PDF and its password are never stored or logged. A new upload replaces the last. `portfolio/service.py::fetch_holdings(..., db)` appends these holdings (broker `cas` is always "read", so deleting the upload drops them from the next snapshot). Not in `mine/lots` or `mine/tax` (stock trades only): MF capital gains are not built.
- `journal_trades`: one doc per broker fill. `_id = "{user}:{broker}:{trade_id}"`, fields `user_id, broker, source`
  (`sync` / `console_csv` / `upstox_history`), `side` ("BUY"/"SELL"), `quantity, price, traded_at, symbol, exchange,
  imported_at`. Index `(user_id, traded_at)` (`journal/store.py::JournalStore.ensure_indexes`). It is written only
  by `::add_trades`, which is insert-only and skips existing `_id`s, so re-sync is idempotent. Readers include
  nearly everything here, via `::list_trades`, which turns naive datetimes into UTC-aware ones.
- `journal_notes`: `_id = "{user}:{round_trip_id}"`, `note, tags, round_trip_id, user_id`. Written by
  `routers/journal.py::set_round_trip_note`.
- `journal_opens`: `_id = "{user}:{IST day}"`. Upserted by `journal/beta.py::record_open` on every `GET /journal`.
- `portfolio_snapshots`: one doc per refresh. Fields `user_id, at, errors, brokers, stale_since, raw_holdings`
  (all brokers, Holding dumps), plus the card: `holdings` (mine-only rows with `verdict, reason_codes, score, health,
  note, previous_verdict, verdict_since`), `totals`, `benchmark`, `concentration`, `summary`, `plan`. Index
  `(user_id, at desc)` (`backend/server.py:131`). Inserted by `portfolio/service.py::refresh_portfolio`; read through
  `::latest_snapshot`.
- `mine_daily`: one row per user per NIFTY trading day. `nifty_value` = NIFTY units (buys add `flow/nifty`; a sale removes
  the fraction of units equal to proceeds / portfolio value just before it, capped at 1; never below 0). Fields `date` (ISO), `flow, invested, value, nifty_value,
  by_symbol{sym:{qty,value}}, partial`. Unique index `(user_id, date)` (`backend/server.py:134`). Written by
  `mine/history.py::_store`, which upserts only changed rows and deletes dates the replay no longer has.
- `holding_theses`: one doc per `(user_id, symbol)` (unique, `mine/thesis.py::ThesisStore.ensure_indexes`). Fields
  `why, target, stop, review_by` (ISO string), `updated_at`.
- `mine_action_state`: `{user_id, action_id, state: dismissed|snoozed, until}` (`mine/actions.py::_set_state`). No
  index is created.
- `corporate_events`: `{symbol, kind: results|ex_dividend, date, amount, source, fetched_at}`. It is market-wide
  (no user_id) and upserted on `(symbol, kind, date)`. A calendar row never overwrites a known amount
  (`mine/events.py::refresh`). `corporate_events_meta {symbol, checked}` limits fetches to one per symbol per IST
  day. Neither has an index.
- `stock_health`: `_id = "{symbol}:{IST day}"`, shared (`portfolio/health.py::stock_health`). `instrument_sectors`:
  `_id = symbol`, 30-day TTL in code (`portfolio/service.py::SECTOR_TTL`).
- `guardrail_events`: `_id = "{user}:{day}:{breach key}"`, inserted with `$setOnInsert`. Index `(user_id, day)`.
  `alert_channels`: `_id = user_id`, `telegram_chat_id`, `telegram_bot_token` (Fernet-encrypted),
  `telegram_bot_username` (`guardrails/store.py`).
- Read only from this area: `suggestions` (ideas, candidates), `paper_trades` (idea exits, AI book P&L),
  `news_items`, `users.role`, `chat_actions`, `autopilot_log`, `broker_credentials`.

**Redis**
- `mine:alert:{user}:{action_id}` NX, TTL 30 days (`mine/actions.py::ALERT_TTL`): one stop/target Telegram per level.
- `digest:pre:{user}:{IST date}` NX, 24h: one pre-market digest a day (`digest.py::send_premarket`).
- `guardrails:tick` NX, 55s: one worker per guardrail tick (`guardrails/monitor.py::run_tick`).
- `levels:{user}:{date}:{bucket}` NX, 30 min (`engine/autorun.py::_level_pass`).
- `rebalance:{user}` rate limit, 10/min (`routers/portfolio.py::rebalance`).
- Telegram bot keys: `telegram:ai:offset:<sha256>`, `telegram:ai:poll-lock:<sha256>` (60s),
  `telegram:ai:history:{user}` (6h, last 10 turns), `telegram:ai:suggest:{user}:{msg}` and `telegram:ai:suggest-last:{user}`
  (6h), `telegram:start:{code}` (15 min), and `chat:{user}` rate limit (20/min) (`telegram_bot.py`).
  `telegram:link:{user}` (15 min) is set in `routers/guardrails.py`.

**Prefs and app settings read here**
- Prefs: `broker_roles`, `account_size`, `rebalance_targets`, `portfolio_max_loss_pct`, `portfolio_max_weight_pct`,
  `guardrails_enabled`, `daily_loss_limit`, `max_trades_per_day`, `cooldown_after_losses`, `cooldown_minutes`,
  `max_option_trades_per_day`, `max_option_lots`, `warn_naked_options`, `auto_square_off` (off/preview/live),
  `autopilot_enabled/live`, `live_strategies`, `max_exposure`, `omniroute_model`.
- App setting: `portfolio_verdicts` (`admin` | `all`), read via `AppSettingsStore.get_portfolio_verdicts`.

## Flows

1. **Journal sync**: `POST /journal/sync`, the 16:00 pass (`scheduler.py::_sync_journals`) and every guardrail
   tick all go through `journal/sync.py::sync_user_trades`. For each broker in `BROKERS` with an ACTIVE session it
   calls `adapter.get_trades()` and then `JournalStore.add_trades(source="sync")`. One broker failing does not stop
   the others.
2. **History import**: `POST /journal/import/zerodha-console` runs `console_csv.py::parse_console_tradebook`
   (422 on a wrong header) and then `add_trades(user,"kite",…,"console_csv")`. `POST /journal/import/upstox-history`
   runs `sync.py::import_upstox_history`, fetching 31-day chunks and skipping IST days that already have live-sync
   fills.
3. **GET /journal**: `routers/journal.py::get_journal`. It records the open, filters with `accounts.py::filter_trades`
   by `account`, then runs `roundtrips.py::build_round_trips`, `mirror.py::costs` (all fills),
   `mirror.py::benchmark` (closed-trip fills only), notes, `news.py::attach_news` and `insights.py::build_insights`.
4. **Portfolio refresh**: `POST /portfolio/refresh` or `portfolio/service.py::daily_reviews` runs
   `portfolio/service.py::refresh_portfolio`, which proceeds as follows.
   1. `::fetch_holdings` reads the ACTIVE brokers and carries the previous snapshot's rows for the others.
   2. Carried rows are repriced from `::_closes` (daily_bars, else yfinance).
   3. `build_scorecard` runs on the mine-role holdings only.
   4. `::_review` adds health, `rules.stock_verdict` / `fund_verdict`, `previous_verdict`, `verdict_since`, and
      `review.write_review` (with `::add_candidates`).
   5. The snapshot is inserted and `hub.publish(user,"portfolio","refreshed")` fires.
5. **GET /portfolio**: `routers/portfolio.py::get_portfolio` reads the latest snapshot. With `live=1` it calls
   `portfolio/service.py::with_live_prices` (broker reads plus quote repricing, nothing stored). It always re-scopes with
   `scorecard_for` to `account`'s brokers (or every broker in `raw_holdings`), passing `verdicts=account != "ai"` so the AI view never carries the review's verdicts. If verdicts are visible it adds
   `with_suggestions`. It adds `thesis_target` and returns `present(snapshot, visible)`.
6. **Rebalance**: `POST /portfolio/rebalance` reprices with `service.quoted`, re-scopes to mine brokers, allows only
   candidates from `routers/portfolio.py::_candidate_symbols`, prices them with `::_closes` (yfinance 5d), and calls
   `rebalance.py::plan_rebalance`. It places no orders: the result is a list of tickets.
7. **Value curve**: `history.py::write_all` (16:00) calls `::backfill` for each user in
   `portfolio_snapshots.distinct(user_id)`, then `::_compute` and `::_store`. `::_inputs` builds the replay events.
   - It uses `mine_trades` (STOCK only, mine brokers) minus MF symbols.
   - Each symbol is scaled by `lots.split_ratio`, and sells are clipped to what the curve holds.
   - It adds a "gap lot" on the first snapshot's day, at its average price, for shares the journal never saw. That
     sets `partial=True`.
8. **Mine overview**: `routers/mine.py::overview` takes `digest.pulse` as the headline and adds XIRR from
   `history.returns`, with dividends from `events.dividends_received` as extra positive flows. It adds the month
   drivers (`::_month_contributions`) and all-time drivers (`pulse.pnl_by_symbol`), plus the mix (`snapshot.concentration`).
9. **Pulse**: `digest.py::pulse` runs `fetch_holdings` for logged-in brokers. Logged-out rows go through
   `service.quoted`, then `scorecard_for` runs on mine brokers. It adds movers (top 3 by |move %|) with
   `headlines_for` (36h). Verdict changes are included only if the snapshot is from the previous weekday or later and
   `verdicts_visible`.
10. **Needs you**: `GET /mine/actions`, Today and both digests call `mine/actions.py::build(db, user, now, show_verdicts)`.
    It merges the following sources:
    - stop/target levels against `exits.mark_prices`
    - open `<user>:mine` paper_trades with `alerted`
    - snapshot `verdict_worse`, `overweight` and `add` (via `rebalance.target_gaps`/`suggest`)
    - negative-direction headlines
    - proven ideas (`risk/paper_gate.py::for_mine`)
    - `review_by` due dates
    - events within 7 days
    - LTCG within 30 days and the Jan–Mar `harvest` (from `tax.report`)

    It then drops ids in `mine_action_state` that are dismissed or snoozed into the future, and sorts by
    `(RANK, -at)`.
11. **Stock page**: `mine/stock.py::detail`. It returns None (404) when the symbol is neither held nor traded. It
    reconciles journal lots with the broker quantity (`lots.reconcile`), and estimates per-lot tax at `LTCG_RATE` or
    `STCG_RATE`. XIRR flows count only shares with a known buy. Verdict history comes from every snapshot, masked
    via `routers/portfolio.py::mask_row` when verdicts are hidden. Trades are split-scaled for the chart.
12. **Tax**: `routers/mine.py::tax` uses mine non-MF raw holdings, `service.quoted` prices, and broker average
    prices, then calls `tax.py::report(mine_trades, held, prices, fy, today, avgs)`.
13. **Guardrail tick**: `guardrails/monitor.py::run_tick` takes the lock and loops over prefs with `guardrails_enabled`, calling
    `::check_user`.
    1. `sync_user_trades(include_pnl=True, skip=ai)` returns `day_pnl` (realised plus unrealised across positions).
    2. Today's trips, excluding the AI broker, go to `guardrails/rules.py::evaluate`.
    3. Each new breach is recorded with `GuardrailStore.record`. `daily_loss` calls `KillSwitchStore.trip`.
    4. `_alert` publishes to the socket and Telegram.
    5. On `daily_loss` with `auto_square_off` set to preview or live, `guardrails/monitor.py::square_off` runs `exit_orders` per non-AI
       ACTIVE broker and places orders only in `live`.
14. **Telegram inbound**: `telegram_bot.py::poll_loop` calls `::poll_once`, which runs `::_poll_bot` per bot route
    (`GuardrailStore.telegram_routes`). It takes a lock and long-polls (25s). It commits the offset before handling.
    It ignores chats with negative ids, then dispatches to `::_reply` (shortcut commands, then `chat.agent.stream_chat`
    with a live draft) or `::_callback` (confirm/confirm2/cancel through `chat.actions.confirm`). Button data is
    `nt:<command>:<id>`; confirm2's id is `<action id>.<confirm_token>` from the first tap (60 bytes, under Telegram's 64), packed and parsed by the aiogram `CallbackData` `::Tap`; data that does not parse is ignored.
    A failed getUpdates logs one line (aiogram errors carry no token) and sleeps `FAIL_BACKOFF_SECONDS` (10) holding the lock.
15. **GET /today**: `routers/today.py::today`. Each part is wrapped in `part()`, which on failure returns None and
    records `errors[name]`. Parts:
    - `_accounts` (60s cache only when every session is ACTIVE)
    - kill switch
    - `autopilot_log` top 5
    - `digest.pulse`
    - `_needs_you` (logins, kill switch, NEEDS_REVIEW suggestions, PROPOSED chat cards, today's guardrail events, a
      `reconcile` item when the latest `broker_reconciliation` day (within `RECON_FRESH_DAYS`=4) has a mismatch
      (`engine/broker_recon.py::summary`), and for admins `data_quality` items from `system/data_quality.py::alerts`,
      link `/lab/handbook`, guarded so a failing check never blanks the list)
    - `_mine_actions` top 3, plus the total
    - `scoreboard` (admin only)
    - `proposals_total`
    - `_autopilot`
    - `_setup` (6 steps)
    - `_backdrop`

## Jobs and schedules

| what | when (IST) | trigger | lock |
|---|---|---|---|
| `journal/sync.py::sync_user_trades` for all users | daily pass, 16:00 | `scheduler.py::_sync_journals` | `scheduler:daily_lock` |
| `portfolio/service.py::daily_reviews`, then a Telegram alert plus `hub` "worsened" when `rules.worsened` | daily pass, after the journal sync | `scheduler.py::run_daily_jobs` | daily lock |
| `mine/history.py::write_all` | daily pass, after reviews | `scheduler.py::run_daily_jobs` | daily lock |
| Weekly mirror Telegram (`mirror.text`, `accounts.ai_vs_me`) | Fridays, in the daily pass | `scheduler.py::_weekly_mirrors` | daily lock |
| `digest.py::send_postclose` | end of the daily pass; skipped if local time < 15:30 (09:20 catch-up); adds a "⚠️ Reconciliation" line only when today's `broker_reconciliation` has a mismatch | `scheduler.py::run_daily_jobs` | daily lock |
| `digest.py::send_premarket` | every auto-run tick; acts only on weekdays 08:45–09:15 | `engine/autorun.py::tick` | `digest:pre:{user}:{date}` NX |
| `mine/actions.py::level_alerts` | auto-run tick in session, every 15-minute bucket (`EXIT_CHECK_MINUTES`) for users with a thesis stop or target | `engine/autorun.py::_level_pass` | `levels:…` NX, plus `mine:alert:…` NX per level |
| `mine/events.py::loop` | every 6h, ingest worker | `datalayer/worker.py::_loops` (`corp_events`) | `corporate_events_meta.checked` per day |
| Guardrail monitor | every 60s, weekdays 09:15–15:35 | `guardrails/monitor.py::start`, from `server.py` lifespan | `guardrails:tick` 55s |
| Telegram poller | continuous long poll | `telegram_bot.py::start`, from `server.py` lifespan | per-bot `poll-lock` 60s |

## Invariants

- **Verdict gate (SEBI).** Verdicts are shown only to admins, or to everyone when `portfolio_verdicts == "all"`.
  - The gate is checked in `routers/portfolio.py::verdicts_visible_to` and `portfolio/digest.py::verdicts_visible`.
  - Non-visible users get `mask_row`: SELL/REVIEW become "REVIEW", everything else None, and `score`, `suggested`
    and `verdict_since` are nulled. `present` also nulls `plan`.
  - Needs-you drops `verdict_worse` and `add` when the gate is closed (`mine/actions.py::VERDICT_KINDS`).
  - `daily_reviews` sends "worth a closer look" instead of the verdict.
  - The `conviction` rebalance rule returns 403 when the gate is closed. AI candidates are listed only when it is
    open.
  - `scoreboard` (You vs Picks) is admin-only in `today.py::today`.
- **Rules decide; AI explains.** `portfolio/rules.py::stock_verdict` scores via `scoring/composite.py::score_intent`, so
  AI_CAP and RULE_FLOOR apply and below the floor the verdict is HOLD. `review.py::write_review` never changes a
  verdict, and it degrades to no prose rather than failing.
- **Nothing here places an order except guardrail square-off.** Actions, rebalance and `suggest` return tickets. The
  one exception is `guardrails/monitor.py::square_off`. It runs only on `auto_square_off == "live"`, only for NSE MIS
  (`guardrails/square_off.py::exit_orders`), and only on brokers that are not the AI broker. It runs at most once per day
  because the `daily_loss` breach is recorded (`GuardrailStore.record`) before any order goes out.
- **Guardrails never touch the AI account.** `skip=ai` applies to sync, trips and square-off
  (`guardrails/monitor.py::check_user`, `::square_off`). The daily-loss breach trips `risk/kill_switch.py::KillSwitchStore.trip`,
  the same limit as the engine kill-switch.
- **Review and verdicts cover the `mine` account only.** `portfolio/service.py::refresh_portfolio` reviews
  `[h for h in holdings if h.broker in mine]` and filters trades the same way. Rebalance, tax, history, lots and
  `mine_holdings` are all scoped to mine. "Held" app-wide means `portfolio/service.py::mine_holdings`, never paper positions.
- **A logged-out broker keeps its holdings.** `portfolio/service.py::fetch_holdings` carries the previous `raw_holdings` for
  every broker not read now.
- **No stale day move.** `portfolio/service.py::quoted` never uses a days-old row's own close as today's base.
- **Ideas shown for Mine come only from proven strategies.** This is enforced by `risk/paper_gate.py::for_mine`, in
  `mine/actions.py::ideas`, `digest.send_premarket` and `portfolio.py::_candidate_symbols`.
- **The journal is idempotent.** `_id = user:broker:trade_id`, insert-only. Note ownership is checked by the prefix
  (`set_round_trip_note` returns 404 otherwise).
- **Telegram safety.** Only private chats (positive id) are accepted (`_poll_bot`). Bot tokens are Fernet-encrypted
  and never returned. Redis keys hash the token. Storing a token without `CREDENTIAL_ENCRYPTION_KEY` raises
  (`guardrails/store.py::set_telegram_bot`). Real-money cards need a second tap (`confirm2`) carrying the server's one-time token; a refused token
  re-arms the card with Confirm/Cancel and sends nothing.
- **Tax rates live only in `mine/tax.py`** (STCG 20%, LTCG 12.5% above Rs 1.25 lakh). `/mine/tax` rejects
  `fy < 2025` (`routers/mine.py::TAX_FIRST_FY`). Long-term means held more than 12 calendar months
  (`tax.py::long_from`).
- **Options and futures stay out of Mine.** `lots.py::mine_trades` keeps `instrument_kind == "STOCK"` only.

## Endpoints

All routes are mounted under `settings.API_PREFIX` (`/api/v1`) with `get_current_user` (`server.py:213,215,240,242`).

| method path | handler | auth | response keys read |
|---|---|---|---|
| GET /mine/overview | `routers/mine.py::overview` | user | `headline{value,day_change,day_change_pct,pnl,pnl_pct,as_of,holdings_as_of,xirr,nifty_xirr}`, `drivers{month,all}{top,bottom}`, `mix{...concentration,count}` |
| GET /mine/history?range=1M\|6M\|1Y\|ALL | `::mine_history` | user | `points[{date,value,invested,nifty_value}]`, `from_date`, `partial` |
| GET/PUT /mine/thesis/{symbol} | `::get_thesis` / `::put_thesis` | user | thesis doc or `{}`; 422 on a bad symbol or stop >= target |
| GET /mine/tax?fy= | `::tax` | user | `realised{short_gain,long_gain,exemption_used,exemption_left,charges,est_tax,rows,uncertain}`, `unrealised`, `turning_long`, `harvest{loss,gain}`, `unknown`, `pre_2018`, `has_history` |
| GET /mine/stock/{symbol} | `::stock_detail` | user | `position`, `lots`, `unknown_qty`, `thesis`, `verdict{current,reasons,note,history}`, `events`, `dividends`, `news`, `closes`, `trades`; 404 if neither held nor traded |
| GET /mine/actions | `::mine_actions` | user | list of `{id,kind,symbol,title,detail,rank,at,action{type,...}}` |
| POST /mine/actions/{id:path}/dismiss, /snooze | `::dismiss_action`, `::snooze_action` | user | `{ok}` |
| GET /portfolio?account=all\|ai\|mine&live= | `routers/portfolio.py::get_portfolio` | user | snapshot minus `raw_holdings`, plus `verdicts_visible`; rows add `suggested`, `thesis_target`; 404 before the first refresh |
| POST /portfolio/refresh | `::refresh` | user | as above; 409 if no holdings and no errors |
| GET /portfolio/rebalance/candidates | `::rebalance_candidates` | user | `[{symbol,price,source,score,preselect}]` |
| POST /portfolio/rebalance | `::rebalance` | user (conviction needs the gate) | `total,cash_left,trades,skipped,excluded,uninvested_pct,stale_since`; 429/409/403 |
| GET /journal?account= | `routers/journal.py::get_journal` | user | `account,round_trips,calendar,insights,brokers_connected,summary{trips,pnl,wins,by_kind},mirror{costs,benchmark}` |
| GET /journal/ai-vs-me | `::ai_vs_me` | user | monthly rows; no caller in `frontend/src/utils/api.js` |
| POST /journal/sync | `::sync_journal` | user | `{imported,brokers,failed}` |
| POST /imports/cas (multipart `file`,`password`) | `routers/imports.py::import_cas` | user | `{funds,transactions,period}`; 422 on wrong password / non-PDF / over 10 MB / NSDL-CDSL |
| GET /imports | `::imported` | user | `{funds,period,imported_at,transactions,trades}` |
| DELETE /imports | `::delete_imported` | user | `{transactions,trades}`: erases the CAS funds, their transactions and this user's `source=console_csv` fills, then re-reads holdings (DPDP) |
| POST /journal/import/zerodha-console | `::import_console_csv` | user | `{imported,duplicates,skipped}` |
| POST /journal/import/upstox-history | `::import_upstox` | user | `{imported,fetched,skipped_synced_days}`; 409 if not logged in, 502 if Upstox fails |
| PUT /journal/round-trips/{id}/note | `::set_round_trip_note` | user (owner prefix) | `{note,tags}` |
| GET /journal/learning | `::get_learning` | user | `backend/learning/report.py::snapshot` |
| GET /journal/beta-metrics | `routers/journal.py::get_beta_metrics` | admin | `beta.py::beta_metrics` keys |
| GET /today | `routers/today.py::today` | user | `market,accounts,live_armed,kill_switch,pulse,needs_you,mine_actions,mine_actions_total,scoreboard,proposals_total,ai_activity,autopilot,setup,backdrop,errors` |
| GET /today/attention | `::attention` | user | `{count}` (`_needs_you` only) |

## Gotchas and known issues

- **CAS funds and broker roles.** `cas` is not a role-assignable broker; `backend/brokers/roles.py::brokers_for` adds `FILE_SOURCES` (`cas`) to the `mine` set whenever roles are set (empty roles still mean "every broker"), and `adapter_for` subtracts it (a file has no adapter). A CAS with no cost for a scheme gets cost = current value (no gain shown). `today.py::_setup` has two import steps (`import_trades`, `import_funds`) linking `/import`.
- **Broker-roles default.** With no `broker_roles` set, `brokers_for` returns `set()`. Most code treats that as "all
  brokers are mine"; `journal/accounts.py::ai_vs_me` now does too (mine = every non-AI broker, AI book empty).
- **Snapshots versus scorecard_for.** The stored card's `holdings` are mine-only, while `raw_holdings` cover all
  brokers. `GET /portfolio` always re-scopes. `scorecard_for` copies verdict, health and note by symbol only, and it
  does not copy `verdict_since`. With `verdicts=False` (the `ai` account) it copies none of them.
- **Action ids contain `:`.** That is why the route uses `{action_id:path}`, with `ACTION_ID` capped at 300 characters.
  Ids pin each instance (`kind:symbol:key`), so a dismissal lasts until the key changes. For `add` the key is
  `verdict_since`.
- **The pre-market digest NX key is set before the work** (`digest.py::send_premarket`) to stop duplicates; a failure
  deletes it again so the next tick retries.
- **`postclose_for` on a non-trading day reads the last trading day.** P&L window and reconciliation use `last_trading_day(today)`, so the `closed` phase of `/today` shows Friday's result, not an empty Saturday.
- **Post-close skips the morning catch-up.** `send_postclose` returns 0 before 15:30 IST, so a 09:20 catch-up pass
  sends no evening message.
- **The Today broker-state cache is per process** (`today.py::_STATE_CACHE`) and is kept only when all sessions are
  ACTIVE.
- **Dividends and splits.** yfinance `t.dividends` are split-adjusted, so `events.py::dividends_received` takes a
  `ratio` (`lots.split_ratio`) and scales the journal quantity; `mine/stock.py` and `GET /mine/overview` pass it.
- **Gaps in the curve.** `history._compute` drops trades dated after the last NIFTY bar. Funds are excluded
  (`funds_excluded`). Unknown shares enter as a gap lot (`partial`).
- **Guardrail trips use the whole journal.** `guardrails/monitor.py::check_user` builds round trips from all fills,
  then keeps trips opened since IST midnight, so closing an older position is not a new (SHORT) trip.
- **Naked-option hedge matching is loose.** Any long option on the same underlying counts as a hedge
  (`guardrails/rules.py::_is_hedged`, `ponytail:` note).
- **Missing indexes.** `mine_action_state`, `corporate_events` and `corporate_events_meta` get none at startup. The
  upserts by `(user_id, action_id)` and `(symbol, kind, date)` are unindexed and have no unique guard.
- **Stock pnl without a price.** `stock.py::detail` reports `pnl` and `pnl_pct` as None when the symbol is held but
  has no price; the realised sum is only used for a fully sold symbol.
- **Past fixes:**
  - 52cc74c: Needs you crashed on an idea with `quantity` None.
  - dbeeff5: the gain harvest suggests whole shares only.
  - dd0cf15: options and futures are left out of lots, tax and the curve.
  - a5b1f17: long-term is measured by 12 calendar months, not 365 days.
  - 29185c1: month drivers ignore trades newer than the stored curve.
  - df531d1: the curve replay deletes stale stored days.
  - 5f0d978: a sell of pre-journal shares leaves the curve.
  - 6742f81: tax FY >= 2025, lasting dismissals, mix count.
  - 8ab7e0d: trustworthy lots, tax and curve.
  - 10804e3: Telegram backs off 10s after a failed getUpdates.
  - 8b3c906: private Telegram chats only; verdict gate in chat.
  - a0384a5: AI-vs-me keeps cross-month trips.
  - d1e3a41: pulse reads the logged-in broker and never measures from a days-old close.
  - fba9955: a logged-out broker keeps its holdings, and the review covers mine only.
  - 5faa0b2: guardrails cover only the user's own account.
  - 4e8297f: rebalance never mixes in the AI book.
  - 22a645b: You vs Picks replaced You vs the AI on Today.
- **ROADMAP Phase 20 known limits.** Trade history comes from Upstox only. A curve before the first known buy uses
  the snapshot cost as one lot. Pre-2018 grandfathering and F&O income are not in the tax figures (`pre_2018` only
  lists symbols).

## Tests

| file | covers |
|---|---|
| backend/tests/test_cas_import.py | CAS mapping (folio merge, zero balance, no cost), upload validation (password, non-PDF, size, NSDL), per-user scoping, delete, empty pages with no broker |
| backend/tests/test_mine_actions.py | Needs-you ranking, stable ids, dismiss/snooze, verdict gate, Jan–Mar harvest, level alerts once, /today reading the list |
| backend/tests/test_mine_history.py | xirr, replay inputs (clip, split, gap lot), `_store` diff and delete, `returns` |
| backend/tests/test_mine_lots.py | FIFO, realised, unmatched, `split_ratio`, `reconcile`, `mine_trades` |
| backend/tests/test_mine_tax.py | FY bounds, `long_from`, set-off, exemption, harvest, turning long |
| backend/tests/test_mine_events.py | `refresh` (amount preserved, once a day), `upcoming`, `dividends_received` |
| backend/tests/test_mine_router.py | `/mine/overview`, `/mine/history` (own user only) |
| backend/tests/test_mine_stock.py | `/mine/stock/{symbol}` |
| backend/tests/test_mine_thesis.py | `/mine/thesis/{symbol}` GET/PUT, validation |
| backend/tests/test_broker_portfolio.py | holdings per broker, `merge`, NIFTY benchmark (phases 1-2) |
| backend/tests/test_portfolio_review.py | health, rule verdicts via composite, AI write-up, verdict switch and masking (phases 3-5) |
| backend/tests/test_rebalance.py | `target_weights`, `plan_rebalance`, `suggest`, `sell_tax` |
| backend/tests/test_portfolio_rebalance_router.py | `/portfolio/rebalance`, candidates, targets, row actions on GET /portfolio |
| backend/tests/test_portfolio_digest.py | pulse, movers and news, verdict changes, scoreboard, premarket/postclose text |
| backend/tests/test_today.py | `GET /today` parts and errors, `/today/attention` |
| backend/tests/test_journal.py | normalisation, round trips, idempotent store, Console CSV, Upstox history |
| backend/tests/test_options_journal.py | instrument kind, by-kind summary, options in guardrails |
| backend/tests/test_journal_insights.py, test_journal_mirror.py, test_journal_news.py, test_journal_beta.py | `build_insights`, `mirror.costs`/`benchmark`, `attach_news`, `beta_metrics` |
| backend/tests/test_account_analysis.py | `journal/accounts.py::ai_vs_me` |
| backend/tests/test_guardrails.py | `rules.evaluate`, once-per-breach alerting, daily-loss kill-switch trip |
| backend/tests/test_square_off.py | `exit_orders`, preview never places, live once a day, AI broker untouched |
| backend/tests/test_telegram_bot.py | inbound bridge: commands, callbacks, private-only, locks/offsets, HTML rendering |
| backend/tests/test_telegram_transport.py (+ `telegram_wire.py`) | Bot API wire: getMe/linking, Start-code scan, 409, long-poll params, sends, HTML fallback, edits, drafts, menu, token-free failure logs |
