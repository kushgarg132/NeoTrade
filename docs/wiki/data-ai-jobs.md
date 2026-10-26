---
page: data-ai-jobs
covers: [backend/datalayer/**, backend/ai/**, backend/chat/**, backend/plan/**, backend/research/**, backend/prompts/**, backend/scheduler.py, backend/llm.py, backend/model_catalog.py, backend/market_cache.py, backend/routers/news.py, backend/routers/chat.py, backend/routers/plan.py, backend/summaries/**, backend/routers/summaries.py]
verified_at: 1943de4
---
# Data layer, AI and background jobs

The ingest worker (`backend/datalayer/`) keeps shared market, macro and news data fresh in Mongo/Redis; the AI features (`ai/`, `chat/`, `plan/`, `research/`) read it through the fact layer and call models only via `llm.py` (OmniRoute gateway, per-feature keys, per-tier models). `scheduler.py` runs the 16:00 IST daily pass. "Jobs and schedules" is the single table of every timer in the backend. AI explains and scores; it never sizes or approves a trade (conviction cap lives in `backend/scoring/composite.py`, not here).

Path notes: `backend/routers/chat.py` does NOT exist. The news HTTP router is `backend/routers/news.py::router`; chat streaming is the WebSocket action `chat` in `backend/ws/routes.py::_stream_chat` (outside this page's globs); chat confirms are `backend/routers/chat_actions.py`. The 2025 `components/`, `agents/`, `mcp_tools/` and `screening/` packages were retired; their live code moved to `ai/analyst.py`, `routers/news.py`, `research/search.py`, `datalayer/stock_info.py`, `chat/lc_tools.py`, `strategies/indicators.py`, `risk/rules.py`, `instruments/indian_stocks.py`, `core/models.py` and `data/fundamentals/`.

## Files

### datalayer (ingest process)
| path | role | key symbols |
|---|---|---|
| `backend/datalayer/worker.py` | ingest entrypoint: leader lock, 16 loops, heartbeats | `worker.py::_loops`, `::run`, `::_run_loop`, `::beat`, `::heartbeat_ages`, `::main` |
| `backend/datalayer/prices.py` | quotes + macro board loops | `prices.py::quotes`, `::macro`, `::macro_rows` (cached rows with `at`, missing tickers left out; `market_data.py::_quotes` fetches only those, also used by `index_move.py::_peers`), `::priority_symbols`, `::last_two`, `::MACRO` |
| `backend/datalayer/news_sources.py` | fetchers: RSS, Google News, GDELT, NSE filings; Nifty 200 csv | `news_sources.py::FEEDS`, `::poll`, `::fetch_rss`, `::fetch_gdelt`, `::fetch_nse`, `::universe_rows`, `::sectors`, `::nifty200_sectors` |
| `backend/datalayer/news.py` | news pipeline: store, triage, prune, score, aggregate, FAILED retries, lag + stall alert | `news.py::poll_loop`, `::process_loop`, `::store`, `::triage`, `::_prune`, `::score`, `::aggregate`, `::followed`, `::valid_impacts`, `::_deep_budget`, `::_score_due`, `::retry_failed`, `::lag`, `::stall_alert` |
| `backend/datalayer/reactor.py` | alerts, news-triggered scans, shadow exits; shared `_claim` | `reactor.py::react`, `::scan`, `::shadow_exits`, `::_claim`, `::hits_for`, `::scan_targets`, `::ai_targets`, `::exit_hit` |
| `backend/datalayer/outcomes.py` | news to price outcomes, theme weights, `proven` | `outcomes.py::record`, `::measure`, `::weights`, `::load_weights`, `::item_weight`, `::proven`, `::loop` |
| `backend/datalayer/market.py` | calendar, FII/DII flows, rule regime, AI brief, `backdrop` | `market.py::calendar`, `::flows`, `::regime`, `::compute_regime`, `::brief`, `::_brief_due`, `::upcoming`, `::top_items`, `::latest_brief`, `::backdrop` |
| `backend/datalayer/bars.py` | `daily_bars` + `fundamentals` stores and loops | `bars.py::loop`, `::fundamentals_loop`, `::read`, `::write`, `::prev_closes`, `::nifty_closes`, `::_due`, `::symbols` |
| `backend/datalayer/analysis.py` | AnalystAgent answer built from stored scored news | `analysis.py::from_layer`, `::_build` |
| `backend/datalayer/catalysts.py` | overnight catalyst map for gap strategies | `catalysts.py::catalyst_map` |

### ai (fact layer, tool runner, grounding)
| path | role | key symbols |
|---|---|---|
| `backend/ai/facts/__init__.py` | fact registry; `as_tools` binds facts to (db, redis, user_id) | `fact`, `FACTS`, `as_tools`, `Fact` |
| `backend/ai/facts/market.py` | market facts (user_id ignored) | `quote`, `price_summary`, `fundamentals`, `news`, `sentiment`, `market_backdrop`, `calendar` |
| `backend/ai/facts/user.py` | user facts (filtered by user_id) + global facts | `portfolio`, `positions`, `journal`, `learning`, `strategy_library`, `game_plan`, `built_strategies`; global: `recent_plans`, `plan_scorecards`, `worst_setups` |
| `backend/ai/runner.py` | capped tool loop, budget hook, repair, single-call fallback | `runner.py::run_with_tools` |
| `backend/ai/grounding.py` | every figure in AI prose must be in the facts | `grounding.py::grounded`, `::unsupported`, `::strip_unsupported`, `::figures`, `::numbers_in` |
| `backend/ai/sentiment.py` | read-only `sentiment:{SYM}` cache; weighted mean | `sentiment.py::get_cached_sentiment`, `::weighted_sentiment`, `::RECENCY_HALF_LIFE_DAYS` |
| `backend/ai/analyst_verdict.py` | read-only `analyst_verdict:{SYM}`; refresh | `analyst_verdict.py::get_cached_verdict`, `::refresh_analyst_verdict` |

### chat
| path | role | key symbols |
|---|---|---|
| `backend/chat/agent.py` | ReAct agent stream: thinking/content/step/action/answer_end/suggestions | `agent.py::stream_chat`, `::_Trailer`, `::NEXT_MARKER`, `::suggest_followups`, `::TOOL_LABELS` |
| `backend/chat/context.py` | day snapshot sent with every message (its `decisions` section, `get_decisions` and the approve action are admin-only: other roles get no engine ideas); profile text | `context.py::build_snapshot`, `::SECTIONS`, `::format_snapshot`, `::format_profile`, `::plan_names` |
| `backend/chat/tools.py` | read tools bound to caller's user_id; `query_my_data` allowlist | `tools.py::read_tools`, `::USER_DATA`, `::SHARED_DATA`, `::_safe_filter`, `::MAX_ROWS`, `::MAX_CHARS` |
| `backend/chat/actions.py` | propose-only action tools + the only executor (`confirm`) | `actions.py::action_tools`, `::ChatActionStore`, `::confirm`, `::_execute`, `::_order_checks`, `::_modify_checks`, `::SETTINGS`, `::ACTION_TTL`, `::CARD_PREFIX`, `::ActionRefused` |
| `backend/chat/account_actions.py` | exit / cancel / modify / stop-loss on role `mine` account | `account_actions.py::propose_exit`, `::propose_cancel`, `::propose_modify`, `::propose_stop`, `::execute`, `::mine_adapter` |
| `backend/routers/chat_actions.py` | HTTP for cards | `chat_actions.py::pending_actions`, `::confirm_action`, `::cancel_action` |

### plan (AI game plan)
| path | role | key symbols |
|---|---|---|
| `backend/plan/builder.py` | pre-open plan: context, tool loop, single-call fallback | `builder.py::build_plan`, `::_context`, `::_plan_with_tools`, `::PlanReply`, `::ground_rationale`, `::MAX_TOOL_ROUNDS`, `::_tell` |
| `backend/plan/validate.py` | pure clamp/filter of model output; fallback plan | `validate.py::validate`, `::TradePlan`, `::fallback_plan`, `::MIN_MULTIPLIER`, `::MAX_PLAN_POSITIONS` |
| `backend/plan/store.py` | `trade_plans` versions, Redis mirror, daily LLM budget | `store.py::save`, `::current`, `::versions`, `::reserve_call`, `::KEY`, `::CALLS_KEY` |
| `backend/plan/gate.py` | `PlanGate` read per bar by the engine; replay source | `gate.py::PlanGate`, `::redis_source`, `::versions_source` |
| `backend/plan/revise.py` | mid-session revisions (ingest loop `plan_revise`) | `revise.py::loop`, `::triggers`, `::may_revise`, `::revise_plan`, `::_revise_with_tools`, `::MAX_REVISIONS`, `::MIN_GAP` |
| `backend/plan/expand.py` | add plan's new symbols to a running intraday run | `expand.py::make_expand` |
| `backend/plan/replay.py` | nightly plan(A) vs no-plan(B) replay; `weeks_beating` | `replay.py::replay_day`, `::replay_all`, `::weeks_beating`, `::SCORECARDS` |
| `backend/plan/notify.py` | Telegram text for plans (not for fallback) | `notify.py::plan_text`, `::notify_plan` |
| `backend/routers/plan.py` | `GET /plan/today` | `plan.py::plan_today` |
| `backend/summaries/core.py` | shared by every AI summary: Redis NX claim per user+kind+period, facts rendered by `::as_facts` with floats rounded to 2 dp, grounded text, failure back-off (6 h), Mongo `ai_summaries` | `core.py::produce`, `::get`, `::latest`, `::shown`, `::FAIL_BACKOFF` |
| `backend/summaries/day.py` | Home "Your day": 3 lines pre-open and post-close, feature `portfolio`, tier `fast` | `day.py::generate`, `::TTL` |
| `backend/summaries/holding.py` | note under each bad-news / results-soon action, cached by action id, feature `news`, tier `fast` | `holding.py::run_all`, `::run_user`, `::note_for`, `::PER_RUN`, `::PER_DAY` |
| `backend/summaries/activity.py` | AI > Activity "what the AI did today and why": autopilot_log + game plan + AI book P&L, feature `plan`, tier `standard` | `activity.py::generate`, `::run_all` |
| `backend/summaries/weekly.py` | weekly report paragraph (what worked, what not, one habit), feature `portfolio`, tier `standard`; also on the Sunday Telegram | `weekly.py::generate`, `::report_facts` |
| `backend/summaries/habits.py` | Journal > Habits "what your trades say": journal fact patterns + costs, feature `learning`, tier `standard` | `habits.py::generate`, `::run_all` |
| `backend/routers/summaries.py` | read-only `GET /summaries/*`, never calls a model | `summaries.py::day`, `::holdings` |

### research, analyst, llm, scheduler
| path | role | key symbols |
|---|---|---|
| `backend/research/graph.py` | LangGraph report: resolve, info, analyst, thesis; no signal | `graph.py::ResearchAgent`, `::ResearchReport` |
| `backend/research/quick.py` | non-AI snapshot (info, 1y bars, technicals, flags) | `quick.py::quick_analysis`, `::_compute_technicals`, `::QuickAnalysis` |
| `backend/research/flags.py` | plain-fact chips, never buy/sell | `flags.py::stock_flags` |
| `backend/research/index_move.py` | AI "why did the index move", Redis-cached | `index_move.py::explain_index_move`, `::_ttl`, `::CACHE_KEY`, `::ExplanationUnavailable` |
| `backend/ai/analyst.py` | per-stock news score + note (2 LLM calls), 4h cache | `analyst.py::AnalystAgent`, `::_score_news`, `::_report`, `::_extract_json`, `::CACHE_TTL_SECONDS` |
| `backend/routers/news.py` | news HTTP router (`/news/feed`, `/news/symbols`, `/news/symbol/{symbol}`) + Google News helpers | `news.py::news_feed`, `::symbol_news`, `::symbol_history`, `::fetch_news_logic`, `::fresh_headlines`, `::fetch_google_news`, `::_title_key` |
| `backend/research/search.py` | query to instrument; optional LLM peers | `search.py::resolve_company_query`, `::_find_peers` |
| `backend/datalayer/stock_info.py` | yfinance company info and price history (logic only, no routes) | `stock_info.py::fetch_stock_info_logic`, `::fetch_price_history_logic` |
| `backend/chat/lc_tools.py` | LangChain tools (stock info, price history, symbol resolve) | `lc_tools.py::fetch_stock_info_tool`, `::fetch_price_history_tool`, `::resolve_symbol_tool` |
| `backend/llm.py` | gateway client, tiers/features, per-user daily cap, key rotation | `llm.py::LLMService`, `::llm_service`, `::get_llm`, `::get_completion`, `::keys_for`, `::_charge`, `::use_model`, `::MultiKeyChain`, `::USER_FEATURES`, `::DailyLimitReached` |
| `backend/model_catalog.py` | gateway model list to Family/Line/Version tree (pure) | `model_catalog.py::build_catalog`, `::FAMILIES`, `::LINES` |
| `backend/market_cache.py` | stale-while-revalidate cache for home feeds | `market_cache.py::cached`, `::_refresh`, `::_claim` |
| `backend/prompts/__init__.py` | `render(name, **values)` strict placeholder check | `prompts/__init__.py::render`, `::_load` |
| `backend/scheduler.py` | 16:00 IST daily pass + lock + catch-up entry | `scheduler.py::scheduler_loop`, `::run_daily_jobs`, `::_run_locked`, `::close_expired_option_positions`, `::_learn`, `::_weekly_mirrors`, `::_sync_journals`, `::LOCK_KEY`, `::LAST_PASS_KEY` |

Prompts (`backend/prompts/*.md`, front matter `system:`; caller in parens): `triage_news`, `score_market_news` (datalayer/news.py); `score_news`, `research_report` (ai/analyst.py); `market_brief` (datalayer/market.py); `index_move` (research/index_move.py); `game_plan`, `game_plan_tools` (plan/builder.py); `game_plan_revision`, `game_plan_revision_tools` (plan/revise.py); `chat`, `chat_followups` (chat/agent.py); `peers` (research/search.py); `resolve_instrument` (instruments/resolve.py); `model_test` (routers/settings.py); `final_turn` (ai/runner.py); `portfolio_review` (portfolio/review.py); `rebalance_ai` (portfolio/ai_rebalance.py); `learning_review` (learning/report.py); `strategy_hypotheses` (learning/hypotheses.py); `strategy_builder`, `strategy_builder_swing` (builder/draft.py).

## Data

### Mongo
| collection | fields that matter | indexes | writers / readers |
|---|---|---|---|
| `news_items` | `_id`=sha1(title key); `title,url,source,published_at,content,scope_hint,fetched_at,attempts`; `status` NEW/TRIAGED/SCORED/IRRELEVANT/FAILED/STALE/DEAD; `failed_at,retries` (FAILED retry schedule; DEAD = out of retries); `scope,themes,region,relevant`; `symbols[]`,`feeds[]`; `impacts[{type,target,direction,impact,horizon}]`,`event`,`material`,`scored_at`; claim stamps `reacted_at,scanned_at,exit_checked_at,outcome_at,planned_at`; `skip_reason`; `expire_at` | TTL `expire_at`; `(status,fetched_at)`; `(impacts.target,published_at)`; `(symbols,published_at)`; `(published_at)` (`news.py::ensure_indexes`, first `poll_loop`) | w: `news.py::store/_triage_batch/_score_batch/_prune`, `reactor.py::_claim`; r: fact `news`, feed router, plan builder, catalysts, `market.top_items`. TTL: IRRELEVANT 7d, relevant 730d |
| `news_outcomes` | `_id`=`{item}:{type}:{target}`; `base,bench,base_at,in_session,scope,themes,direction,impact`; `ret_/bench_/move_` for `1h,1d,5d` | `base_at` | `outcomes.py` |
| `news_theme_weights` | `_id`=`scope|theme|sign`; `weight,hit_rate,n,at` | none | w: `outcomes.weights` (weekly) |
| `macro_series` | `_id`=`{ticker}:{IST date}` or `{FII|DII}_NET:{date}`; `value,at` | none | w: `prices.macro`, `market.flows` |
| `econ_calendar` | `_id`=`{date}:{country}:{title}`; `at,country,title,impact` High/Medium,`forecast,previous` | none | w: `market.calendar`; r: `market.upcoming`, `revise.triggers` |
| `daily_bars` | `symbol,date`(YYYY-MM-DD IST),`open,high,low,close,volume` adjusted | unique `(symbol,date)`, created on first `bars.loop` pass | w: `bars.write` (delete then insert); r: `bars.read/prev_closes`, fact `price_summary`, quick analysis |
| `fundamentals` | `_id`=symbol; FundamentalSnapshot fields + `as_of` | none | w: `bars.fundamentals_loop`; r: fact `fundamentals` |
| `trade_plans` | `user_id,date,version,at,trigger,skip_day,risk_multiplier,max_positions,add_symbols,allow[{symbol,strategies}],exits,rationale[],scope[]` | unique `(user_id,date,version)` (`save` retries once on `DuplicateKeyError` with the next version, then raises) | w: `plan/store.py::save`; r: `versions`, revise, replay, facts |
| `plan_scorecards` | `user_id,date,a{net,max_drawdown,trades,win_rate},b{...},plan_versions,at` | none | w: `replay_day`; r: `/plan/today`, fact `plan_scorecards` |
| `chat_actions` | `id,user_id,kind,params,summary,venue,needs_second_tap,message`; `status` PROPOSED/CONFIRMED/CANCELLED/EXPIRED/FAILED; `result,created_at,expires_at,confirmed_at` | unique `id`; `(user_id,status)` (`ChatActionStore.ensure_indexes`, called from `server.py` startup) | w: `ChatActionStore`; r: `query_my_data` |
| `autopilot_shadow` | `user_id,at,side=SELL,symbol,quantity,product,venue,news_id,title,impact` | not here | w: `reactor.shadow_exits` |
| `app_settings` (`_id:"singleton"`) | `llm_model,llm_tiers.{fast,standard,deep},llm_features_off[],lab_enabled,portfolio_verdicts` | n/a | `app_settings.py::AppSettingsStore` (admin writes via routers/settings.py) |
| read only here | `instruments, watchlist, paper_positions, portfolio_snapshots, user_prefs, trading_runs, paper_trades, journal_*` | | priority symbols, plan context, chat tools |

### Redis (client uses decode_responses=True, so values are str)
| key | value / TTL | writer |
|---|---|---|
| `ingest:leader` | token, 30s, renewed every 10s | `worker.py::run` |
| `ingest:heartbeat:{loop}` (also `leader`) | unix s; TTL `max(300, 2*interval)` | `worker.py::beat` |
| `quote:{SYM}` | `{ltp,prev_close,at}`; 120s priority / 900s universe in session / 1800s off session | `prices.py::_quote` via `marks.store_quotes` |
| `macro:{yf ticker}` | `{name,symbol,value,change,percent,at}` 600s | `prices.macro` |
| `sentiment:{SYM}` | float str; 24h from `news.aggregate` (every followed name, absent when no news); 4h when written by `AnalystAgent._store`, which never shortens a longer TTL | `news.aggregate`, `agent.py::_store` |
| `sector_sentiment:{sector}`, `market:sentiment` | `{score,n,at}` 24h | `news.aggregate` |
| `analyst_verdict:{SYM}` | `{sentiment_score,impact_score,label,top_reason}` 25h | `refresh_analyst_verdict` only (daily pass, curated symbols; `news.aggregate` no longer writes it) |
| `analyst:{SYM}`, `analyst:lock:{SYM}` | note JSON incl. `basis`, 4h; lock 120s | `analysis.from_layer`, `AnalystAgent` |
| `news:deep_calls:{IST date}` | int, 2d | `news._deep_budget` |
| `news:stall_alert:{triage,backlog,score}` | "1", 2h (one admin alert per condition per 2h) | `news.stall_alert` |
| `news:alerted:{user}:{target}`, `news:scanned:{user}:{sym}`, `news:shadow:{user}:{sym}` | "1": 3600s / 24h / 24h | `reactor.py` |
| `news:theme_weights` (no TTL), `news:theme_weights:due` (7d) | `{key: weight}` | `outcomes.weights` |
| `market:regime` 1h, `market:brief` 48h, `market:brief:backoff` 600s, `market:flows` 4d | JSON | `market.py` |
| `bars:as_of`, `bars:full_at:2009-01-01`, `fundamentals:as_of` | IST date str, no TTL | `bars.py` |
| `market:{indices,movers,global,news}`, `market:{key}:refreshing` (60s) | `{at,data}` SWR cache, no TTL | `market_cache.py` (callers `routers/market_data.py`, `analyst/news.py`) |
| `index_move:{ticker}` | explanation JSON; 15 min while session is today, else until next 09:15 IST (60s..6h) | `index_move.py::_ttl` |
| `plan:{user}:{IST date}` | current plan JSON; until 01:00 IST next day | `plan/store.py::save` |
| `plan:calls:{IST date}` | int, 2d | `store.reserve_call` |
| `plan:regime_seen`, `plan:event:{id}` | 86400s | `revise.py::triggers` |
| `plan:build:{user}:{date}` | worker token, 3600s | `engine/autorun.py::_preopen_plans` |
| `scheduler:daily_lock` 2h; `scheduler:last_pass` no TTL | token; IST date | `scheduler.py::_run_locked` |
| `job:last:{name}` hash `at,ok,note` | `daily_pass, data_quality, autorun, order_sweeps, guardrail_monitor, telegram, strategy_builder` | `system/jobs.py::mark` |
| `rate:llm:{user}:{IST date}` | per-user LLM calls, 2d | `llm.py::_charge` via `rate_limit.allow` |
| `llm:last_ok` (epoch s), `llm:last_error` (`{at,error}`) | 86400s; every `get_completion` success / exception | `llm.py::_note`; r: `data_quality.py::_llm` |

### Settings
Env (`backend/configs/settings.py`): `NEWS_LLM_CALLS_PER_DAY=200`, `USER_LLM_CALLS_PER_DAY=150`, `PLAN_LLM_CALLS_PER_DAY=100`, `AI_TOOLS_ENABLED=True`, `OMNIROUTE_BASE_URL/MODEL`, `OMNIROUTE_API_KEY(S)`, `OMNIROUTE_FEATURE_KEYS` {feature: key}. Admin runtime switches (`app_settings.py`, 30 s cache per process): model per tier (`TIERS` fast/standard/deep), `FEATURES` = news, plan, research, chat, portfolio, learning (on/off), `lab_enabled` (default off). Per-user prefs read here: `universe, account_size, max_exposure, per_trade_cap, news_alerts` (held|held+watched|all|off), `autopilot_enabled, autopilot_news, autopilot_live, broker_roles, omniroute_model`.

## Flows

1. News ingest to sentiment (ingest worker, leader only)
   1. `news.py::poll_loop` (60s): `followed()` = Nifty 200 (`news_sources.universe_rows`, csv `backend/factor/nifty200.csv`) + `prices.priority_symbols`; alias regexes rebuilt only when the name set changes (`build_aliases`); `news_sources.poll` fetches sources that are due (`_due`, cadence in `FEEDS`); `news.store` upserts by `item_id(title)` (`$setOnInsert` + `$addToSet` symbols/feeds). NSE filings (`feed=="nse"`) start TRIAGED; `gnews_symbol` tags are kept only if `names_company`.
   2. `news.py::process_loop` (300s): if (`near_session` or 3600s since last LLM pass) and `feature_enabled("news")`: `triage` (fast tier, 150 headlines per call; 1 call in session, 2 off session; invalid JSON retried once by `_ask`; 3 failed attempts set FAILED + `failed_at`; `triage` first runs `retry_failed`: FAILED published over 3d ago goes STALE, FAILED with `retries` >= 3 goes DEAD (never retried), rows without `failed_at` get it set to now (legacy start), then up to `RETRIES_PER_PASS` (20) FAILED rows due 1h/6h/24h after their last failure (by `retries` 0/1/2) go back to NEW (no `triaged_at`) or TRIAGED with `attempts=2` (one more try) and `retries+1`; triage and score order retried rows after every fresh one, so they spend the same budgeted calls only when room is left; an outage reply (`LLM_DISABLED` / `Error generating response…`) returns `_OUTAGE` and counts no attempt, so a provider outage never fails items) then `_prune` (TRIAGED items to IRRELEVANT with `skip_reason` other_script / unfollowed / duplicate at Jaccard >= 0.7 over 24h).
   3. Scoring: `_deep_budget(redis,1)` reserves one deep call per pass; in session only if `_score_due` (>=20 TRIAGED, or a priority symbol waits, or the oldest waited 10 min); off session whenever any TRIAGED waits. `score` marks TRIAGED older than 3d STALE, orders priority-symbol items, then MARKET/MACRO/GLOBAL, then the rest; max 40 items per call; `valid_impacts` drops unknown sectors/symbols and clamps direction -1..1, impact 0..10; `material` = any impact >= `MATERIALITY_THRESHOLD` (6, `strategies/longterm/analyst_verdict.py`).
   4. `aggregate` (after any scoring, else every 10 min): per (type,target) points weighted by `outcomes.item_weight` then `ai/sentiment.py::weighted_sentiment` (impact^2 x 0.5^(age/30d)) over 60 days; `sentiment:{SYM}` = 0.6 company + 0.25 sector + 0.15 market (`_blend`, clamped), sector/market JSON. It does not write `analyst_verdict:{SYM}` (the daily refresh owns it).
2. News reactions (ingest; all use `reactor.py::_claim(field, now, fresh_only=True)`: SCORED + material + field unset; user-facing reactions (`reacted_at`, `scanned_at`, `exit_checked_at`, `planned_at`) also need scored in last 30 min + published in last 6h; `outcome_at` passes `fresh_only=False`, so outcome bookkeeping catches up every scored item after an outage (200 per pass); stamps the field before any work)
   - `react` (60s, `reacted_at`): `_audience` (held = real broker holdings via `portfolio.service.mine_holdings`, watchlist, `news_alerts` pref) then `hits_for` then one alert per user+target per hour (`ALERT_KEY` SET NX) then `_deliver` (WS topic `news`/`alert` + Telegram `suggestions.notify.notify`). Market shock = INDIA impact >= 7.
   - `scan` (120s, `scanned_at`): per scan-enabled user, `scan_targets` inside their universe (none for a COMPANY-scope item while `reactor.py::COMPANY_SCAN_PAUSED`, owner decision 2026-10-26: company direction hit 42-43% vs NIFTY), <=20 symbols/user/pass, once per user+symbol per day, then `suggestions.scan.scan_universe(source="news")`, `attach_theses`, Telegram. If `autopilot_enabled` and `autopilot_news` and Lab on: stock proposals moved by a `proven` theme go to `engine/autorun.py::_autopilot_proposals(source="news")`.
   - `shadow_exits` (60s, `exit_checked_at`): impact >= 8 and direction <= -0.5 on a held long of a user with `autopilot_news` inserts `autopilot_shadow`; places nothing.
   - `outcomes.loop` (300s): `record` (`outcome_at`, any age; an item scored over 30 min ago is priced from `daily_bars` closes at publication (IST; before 15:30 means the prior close), or flagged `late: true` with the live snapshot when bars are missing, and `compute_weights` skips `late` rows; snapshot from `quote:` / `macro:^NSEI`), `measure` (+1h only if snapshot was in session, +1d, +5d; horizons missed by >12h stay empty), `weights` (once per 7d via SET NX; needs >=20 samples per key; weight = 1+2(hit-0.5) clamped 0.5..1.5).
3. Backdrop: `regime` (60s, no LLM) = `compute_regime(market:sentiment, macro:*, market:flows, next-30-min High event)` to `market:regime` (risk_off <= -0.5, risk_on >= 0.3). `brief` (60s) = `_brief_due` then `render("market_brief")`, tier standard, feature news, to `market:brief`; skipped when the top-25 items and regime are unchanged; failure sets a 600s backoff. `market.py::backdrop(redis)` is what chat, notes, plan and the autopilot fence read; it returns `as_of` and replaces the brief text with "brief unavailable (stale since ...)" when older than 12 h in session hours or 36 h otherwise.
4. Stock AI report (WS `analyze`, 10/min/user; `ws/routes.py::_stream_analysis`): `use_model(user pref, user_id)` then `ResearchAgent.run` (resolve, `fetch_stock_info_logic`, `AnalystAgent.analyze`, thesis comes from the same call) then `analysis.py::from_layer` (needs `ingest:heartbeat:news_process` < 15 min and the symbol in `followed`; reads <=5 scored company items in 30d + `sentiment:`; cached note reused while `basis` = `{newest_item_id}:{sentiment:.2f}` is unchanged; one writer per symbol via `analyst:lock`) else `analyst:{SYM}` 4h cache else `_analyze` (Google News, `_score_news` deep + `_report` standard, both feature `research`) and `_store` (also writes `sentiment:`); a failed score or report (`sentiment_analysis.scored` false) is returned but never cached, and `_rescored` then leaves the suggestion score unchanged.
5. Quick analysis (WS `quick_analyze`, 60/min, no LLM): `quick.py::quick_analysis` = `resolve_company_query` + `fetch_stock_info_logic` + `StoreHistoryProvider` 1y daily bars, `_compute_technicals`, `stock_flags`.
6. Index explanation: `GET /market/index/{ticker}/analysis` (routers/market_data.py) to `index_move.py::explain_index_move`: Redis hit returns `cached:true`; else yfinance session + stored top headlines (`market.top_items`, Google fallback) + peers (`macro_rows`) + movers, tier standard, feature research; failure raises `ExplanationUnavailable` (HTTP 503).
7. Chat message (WS `chat`, 20/min, `ws/routes.py::_stream_chat` then `chat/agent.py::stream_chat`):
   1. `llm_service.get_llm(tier="deep", feature="chat")`; None gives "The AI service is not available right now."; `use_model(user_id)` makes `get_llm` charge `rate:llm:` and `DailyLimitReached` becomes the allowance message.
   2. `context.build_snapshot` (market backdrop + sections portfolio/broker/decisions/paper/limits, each failure isolated) + `_profile`, rendered into `prompts/chat.md`; history turns replayed.
   3. `create_react_agent(llm, read_tools + action_tools)` streamed with `astream_events`; `_Trailer` hides everything after `<<<NEXT>>>` (follow-up chips ride the same call); a tool result starting `ACTION_CARD:` becomes an `action` event; `suggest_followups` (fast tier) runs only if the model gave none.
   4. The WS drops `step`/`answer_end` (Telegram-only; `guardrails/telegram_bot.py` consumes them).
8. Chat action confirm (`POST /chat/actions/{id}/confirm`): `actions.confirm` does `ChatActionStore.claim` (atomic PROPOSED to CONFIRMED, owner, unexpired, 5 min TTL); `needs_second_tap` without `confirm_token` flips back to PROPOSED and returns `NEEDS_SECOND_TAP` + `confirm_token` (`risk/live_confirm.py::issue`); with one, `live_confirm.redeem` spends it (a refusal flips back to PROPOSED and raises `TokenRefused`, 409, or 403 for another user's token; the route answers `{detail, code}` via `TokenRefused.response()`) before anything runs; the `approve` kind then calls `routers/suggestions.py::place_live_approval` (the card's token was the second tap); `_execute` re-checks from the DB (never trusts the card) then calls existing code: approve/decline via `routers/suggestions`, `paper_run` via `routers/trading.launch_run`, `setting` via `PrefsStore.update` (allowlist `SETTINGS`), `order` via `_order_checks` + `suggestions.service.execute_live_order`, `ai_order` via `autopilot.service.submit`, `strategy` via `routers/settings.submit_strategy`, `memory` via `ProfileStore.add_memory`, `exit/cancel_order/modify_order/stop_loss` via `account_actions.execute` (market must be open, `mine` account only). `ActionRefused` becomes HTTP 409.
9. Game plan build: `engine/autorun.py::_preopen_plans` (08:45 to 15:30 IST weekdays, Lab "the AI game plan build", per-user lock `plan:build:`, requires `live_feed_ready`, skipped if a plan exists) then `builder.build_plan`: strategies = intraday minus `load_rules(...).paused` (none left = fallback, no call); `_context` (candidates = universe + held/watched + <=30 catalyst names, cached sentiment, 18h headlines, strategy catalog, regime, brief, flows, 8h calendar, caps); production path `_plan_with_tools` (tools `price_summary,news,fundamentals,positions`, <=2 rounds, tier deep, feature plan, `reserve_call` per round, `PlanReply` schema, `validate`, `ground_rationale` drops rationale lines with ungrounded figures), else the single `_llm` call (<=2 attempts, each reserves budget); any failure stores `fallback_plan(...)`. `store.save` writes `trade_plans` + `plan:{user}:{date}`; `_tell` sends Telegram unless the trigger is fallback.
10. Plan revision (`revise.loop`, ingest 60s, in session only, Lab "AI game plan revisions"): plans = today's non-fallback plans; `triggers` = scored items hitting plan scope/held names or their sectors (`planned_at` claim), `market:regime` label change vs `plan:regime_seen`, a High calendar event that passed 5-15 min ago; `may_revise` = <2 revisions today and >=15 min since the last version; `revise_plan` via `_revise_with_tools` (tools `news,price_summary,positions`) else single call; `revised.scope` is the union with the old scope (never shrinks); triggers landing while a user is rate-limited are dropped.
11. Plan at execution: `routers/trading.py` builds `PlanGate(redis_source(...))` for INTRADAY runs; `engine/runner.py` calls `plan.refresh(bar.timestamp)` per bar, `plan.blocks(...)` before opening intents, `plan.multiplier` shrinks size, `plan.adds/exits` feed `expand.make_expand` and `_plan_exit_orders`. `PlanGate.blocks` order: skip_day, symbol outside `scope` untouched, not in allow, max_positions. Fallback plan gates nothing; a read failure means no plan.
12. Tool runner `runner.py::run_with_tools`: `AI_TOOLS_ENABLED` off, no model, any exception, or no reply goes to `fallback()`; every model call (final and repair turns included) first awaits `reserve()`; tools run concurrently per round (`asyncio.gather`); tool errors become `{"error"}` JSON; a schema parse failure gets one repair call. Facts collected in `result["facts"]` feed `grounding`.
13. Every LLM call: `get_llm(tier, feature)` returns None (so `get_completion` returns `"LLM_DISABLED"`) if the feature is switched off or no key exists; other failures come back in-band as `"Error generating response: ..."`; model = per-user override (`use_model`) else admin tier model else `OMNIROUTE_MODEL`; key = `keys_for(feature)` (the feature's own key alone, else the shared list wrapped in `MultiKeyChain` fallback).
14. Daily pass (`scheduler.py::run_daily_jobs`) order: `builder_store.refresh`; `SuggestionStore.expire_stale`; `close_expired_option_positions`; `_refresh_analyst_verdicts` (each `FO_UNDERLYINGS`, needs redis); per scan-enabled user `scan_universe` + `attach_theses` + `for_mine` Telegram; `_sync_journals`; `_reconcile_brokers` (-> `engine/broker_recon.py::run_all`, today's pass only, result `reconcile_mismatches`); `_learn` (Lab "nightly learning"; Fridays also `weekly_text`); `plan/replay.py::replay_all`; `learning.retune.start_if_due`; `builder.draft.start_if_due`; `portfolio.service.daily_reviews`; `mine.history.write_all`; `forecast.picks.run`; `forward.score.score_due` (own try, `mark(redis, "forward", not failed, ...)` → `job:last:forward`, failed when any record raised); Friday `_weekly_mirrors`; `portfolio.digest.send_postclose` (returns 0 before 15:30). Then `_run_locked` sets `scheduler:last_pass`, `mark(DAILY_PASS)`, `_data_quality` (never gates; `check(db, redis)` marks `data_quality` failed when its `failures` list is non-empty). The first three steps are not wrapped in try, so an exception there aborts the pass (logged by `scheduler_loop`); the later steps are each wrapped.

## Jobs and schedules

All times IST. `in_session` = NSE trading day (`core/market_calendar.py::is_trading_day`: Mon-Fri minus the static holiday set) 09:15 to <15:30 (`engine/autorun.py::in_session`). `near_session` = in_session or in_session(now+45 min), i.e. from 08:30 (`autorun.py::near_session`). "Every" for ingest loops is the sleep AFTER a pass (`worker.py::_run_loop`), not a fixed rate. A loop's heartbeat is written only when its pass did not raise.

| Job | Process | When | Entry | Lock / gate |
|---|---|---|---|---|
| Leader election | ingest | renew every 10s, TTL 30s; lost = `os._exit(1)`, Docker restarts | `worker.py::run`, `::main` | `ingest:leader` |
| `quotes` | ingest | 15s pass: in session priority (held/watched) every pass, Nifty 200 + priority every 5 min; off session everything every 10 min | `prices.py::quotes` | leader |
| `macro` | ingest | 60s | `prices.py::macro` | leader |
| `news_poll` | ingest | 60s pass; feeds due per `FEEDS` cadence 60/120/300s, GDELT 300s, NSE filings 60s, per-sector Google 900s, 5 symbols per pass (priority symbols re-searched every 900s) | `news.py::poll_loop` | leader |
| `news_process` | ingest | 300s; in `near_session` triage + score each pass; off session only once per 3600s (2 triage batches, scores any waiting) | `news.py::process_loop` | leader; `feature_enabled("news")`; `NEWS_LLM_CALLS_PER_DAY`; in session also the stall alert (`news:stall_alert:*` 2h) |
| news aggregate | ingest | after scoring, else every 10 min | `news.py::aggregate` | inside `news_process` |
| `calendar` | ingest | 6h | `market.py::calendar` | leader |
| `flows` | ingest | 30 min | `market.py::flows` | leader |
| `regime` | ingest | 60s | `market.py::regime` | leader |
| `brief` | ingest | 60s check; writes on: first brief of the near-session run-up, new material MARKET/MACRO/GLOBAL item (min gap 15 min), hourly in session only if regime label changed, off session every 6h; 600s backoff after failure | `market.py::brief`, `::_brief_due` | leader; feature `news` |
| `news_react`, `news_scan`, `news_exits` | ingest | 60s, 120s, 60s | `reactor.py::react/scan/shadow_exits` | leader; scan's autopilot hand-off needs Lab |
| `news_outcomes` | ingest | 300s; theme weights at most weekly | `outcomes.py::loop` | leader |
| `bars` | ingest | polled every 15 min; works only after 15:45 once per IST day (`bars:as_of`), or at once if never filled; full 2009 re-download every 7 days (`bars:full_at:2009-01-01`), otherwise last month | `bars.py::loop`, `::_due` | leader |
| `fundamentals` | ingest | polled every 30 min; once per IST day (`fundamentals:as_of`), concurrency 4 | `bars.py::fundamentals_loop` | leader |
| `plan_revise` | ingest | 60s, in session only | `revise.py::loop` | leader; Lab "AI game plan revisions"; <=2 revisions per user per day, 15 min apart |
| `corp_events` | ingest | 6h | `mine/events.py::loop` (outside this area) | leader |
| Daily pass | API (any worker) | 16:00 Mon-Fri (`RUN_HOUR=16`; weekends skipped) | `scheduler.py::scheduler_loop` then `_run_locked` | `scheduler:daily_lock` 2h; skipped if `scheduler:last_pass` >= the day |
| Daily pass catch-up | API | first tick at/after 09:20 when `last_pass` < previous trading day | `autorun.py::_longterm_pass` then `_catch_up` then `scheduler._run_locked(pass_day=missed)` | same lock; background task |
| Monthly re-tune | subprocess (`nice -n 15`) | once per calendar month, first daily pass with Lab on | `learning/retune.py::start_if_due` | Lab "the monthly re-tune"; `retune_runs` month doc |
| Strategy builder | subprocess (`nice -n 15`) | Friday pass, once per ISO week | `builder/draft.py::start_if_due` | Lab "the weekly strategy builder"; unique `week`; `builder:lock` |
| Nightly learning | API (daily pass) | 16:00 pass; weekly note Fridays | `scheduler.py::_learn` | Lab "nightly learning" |
| Plan replay | API (daily pass) | 16:00 pass | `plan/replay.py::replay_all` | not Lab-gated; needs an INTRADAY run and plan versions that day |
| Auto-run tick | API (every worker) | 60s | `autorun.py::autorun_loop` then `tick` | Redis `autorun:{slot}` ownership; intraday needs Lab "the intraday auto-run" |
| Login reminders | API | 08:30 to 09:05 ("early"), 09:05 to 09:15 ("late"), once each per user | `autorun.py::_login_reminders` | SET NX per user/day/slot |
| Pre-market digest | API | 08:45 to 09:15, once a day per user | `portfolio/digest.py::send_premarket` | `digest:pre:{user}:{date}` |
| AI summary: Your day | API (with the digests) | with the 08:45 pre-market digest (08:45 to 09:15) and with the post-close digest after the 16:00 pass; 2 calls per user per day | `digest.py::_day_summary` then `summaries/day.py::generate` | `summary:day:{user}:{date}:{phase}` SET NX 30h; feature `portfolio` (fast); failure waits 6h |
| AI summary: holding notes | API (every tick) | per user at most every 30 min, 08:45 to 22:00; at most 4 new notes a run and 12 a day, one per new action id | `autorun.py::tick` then `summaries/holding.py::run_all` | `summary:holding:run:{user}` 30 min, `summary:holding:{user}:{action id}` 15d, day counter; feature `news` (fast) |
| AI summary: AI activity | API (daily pass) | 16:00 pass (not a next-morning catch-up), once per user per IST day, for users with an autopilot log row or a plan today | `scheduler.py::run_daily_jobs` then `summaries/activity.py::run_all` | `summary:activity:{user}:{date}` SET NX 30h; feature `plan` (standard) |
| AI summary: weekly report | API (autorun tick) | Sunday from 18:00 with the weekly report, once per user per ISO week | `reports/weekly.py::send` then `summaries/weekly.py::generate` | `summary:weekly:{user}:{week}` SET NX 8d inside the report's own `report:weekly:` guard; feature `portfolio` (standard) |
| AI summary: habits | API (daily pass) | the week's last trading day's 16:00 pass, once per user with journal trades per ISO week | `scheduler.py::run_daily_jobs` then `summaries/habits.py::run_all` | `summary:habits:{user}:{week}` SET NX 8d; feature `learning` (standard) |
| Game-plan build | API | 08:45 to 15:30 trading days, per auto-intraday user with a live broker feed, until a plan exists | `autorun.py::_preopen_plans` | Lab "the AI game plan build"; `plan:build:` 1h; `PLAN_LLM_CALLS_PER_DAY` |
| Long-term exits / level alerts | API | in session, every 15-min bucket | `autorun.py::_longterm_pass`, `::_level_pass` | `longterm:{user}:{day}:{bucket}`, `levels:...` |
| Morning pass | API | first tick at/after 09:20, once a day per user (catch-up, monthly factor rebalance, picks entry, autopilot proposals, digest) | `autorun.py::_longterm_pass` | `longterm:{user}:{day}:morning` |
| Order sweeps | API | 60s | `engine/sweeps.py::_loop` | compare-and-set per row |
| Guardrail monitor | API | 60s, in session | `guardrails/monitor.py::monitor_loop` | `LOCK_KEY` 55s |
| Telegram poller | API | long poll 25s + 0.5s pause; 10s backoff on error | `guardrails/telegram_bot.py::poll_loop` | one poller per bot, lock 60s |
| Price pump | API | 15s | `ws/pump.py::pump_loop` | none |
| Worker heartbeat | API and jobs | `worker:alive:{boot}` every 30s (TTL 90s) | `runs.py::keep_alive` | none |
| Instrument expand | API | once at startup (20h marker) | `server.py::_expand_instruments` | none |
| Home feeds cache | API (on request) | SWR: indices/global 60s, movers 300s, market news 600s; refresh claim 60s | `market_cache.py::cached` | `market:{key}:refreshing` |
| Analyst note cache | API (on request) | 4h per symbol | `ai/analyst.py` | `analyst:lock:{SYM}` 120s |
| User LLM allowance | API (on request) | 150 chat/research LLM calls per user per IST day; WS limits analyze 10/min, quick 60/min, chat 20/min | `llm.py::_charge`, `ws/routes.py::_BUDGETS` | |

Lab switch (`app_settings.lab_enabled`, default off, seen by every process within 30 s; `app_settings.py::lab_on` logs one info line per job per day when skipping): gates exactly seven call sites: `scheduler.py::_learn`, `autorun.py::_preopen_plans`, `autorun.py::tick` (intraday auto-run; running slots stop as if turned off), `reactor.py::_scan_user` (only the autopilot hand-off; the scan and its proposals still happen), `learning/retune.py::start_if_due`, `plan/revise.py::loop`, `builder/draft.py::start_if_due`. NOT Lab-gated: news pipeline, brief, regime, daily scan, analyst verdicts, plan replay, chat, research. The per-feature switch (`feature_enabled`) is separate: it makes `get_llm` return None and stops `process_loop` triage/scoring.

## Invariants

- Chat never executes: action tools only call `ChatActionStore.propose`; `confirm` is the only executor, claims atomically, re-runs checks and needs the server-checked second tap (`risk/live_confirm.py`: the first call returns `NEEDS_SECOND_TAP` + `confirm_token`, random, single use, 60 s in Redis `live_confirm:<token>`, bound to user + action/suggestion id + a hash of the order terms; the placing call must present it; missing/spent/expired/other-terms -> 409, another user's -> 403, no order; every refusal carries a `code` beside the text: `confirm_missing` (no token), `confirm_expired` (no such token in Redis: expired, spent by an earlier tap or never issued, which Redis cannot tell apart), `confirm_spent` (lost a race to a rival tap), `confirm_mismatch` (order terms or target changed), `confirm_other_user` (403)) for every `needs_second_tap` card (`actions.py::confirm`, `::_execute`). Cards for the user's own account go to role `mine` only (`account_actions.py::mine_adapter`, `actions.py::_active_broker`); `ai_order` goes through `autopilot.service.submit` (fence) and its venue must equal the autopilot mode.
- No paper approvals or paper orders from chat: `PAPER_ORDERS_GONE`, `PAPER_APPROVALS_GONE` (`actions.py`).
- Chat reads are scoped by closure `user_id` (no tool takes a user id); `query_my_data` allowlist `USER_DATA`/`SHARED_DATA`, filter ANDed with `{"user_id": user_id}`, `$where/$function/$accumulator` banned, `_id,user_id` hidden, 100 rows / 15000 chars cap; portfolio snapshots pass through `present(..., verdicts_visible)` (SELL/ADD admin-only gate) in `query_my_data` and in fact `portfolio`.
- User facts require a user: `as_tools` raises `ValueError` for `user=True` facts without `user_id` (None would match legacy ownerless rows). A fact never raises: errors come back as `{"error"}` with `as_of`/`source` (`facts/__init__.py::fact`).
- The game plan only tightens (`validate.py`): multiplier clamp 0.25..1.0, max positions <= 10, `allow` limited to known strategies and universe+adds (adds must be Nifty 200 names, <=10), no catalyst field from the model, exits dropped for `pre_open`/`fallback` triggers; `PlanGate` only blocks or shrinks openings; any exception means trading without a plan (`gate.py::refresh`).
- Every plan LLM call goes through `store.reserve_call`; news deep calls through `_deep_budget`; user chat/research through `_charge`.
- Figures in AI prose must come from the call's facts (`grounding.py`); plan rationale is filtered with it; ungrounded sentences are dropped, not rewritten.
- One sentiment source for conviction: `sentiment:{SYM}`, written by `news.aggregate` for followed names; for those, the analyst note never writes `sentiment:` when the ingest layer answered (`AnalystAgent._store_note`).
- AI summaries (`backend/summaries/`) are written only by their job at the cadence in the table above (Redis NX per user+kind+period); `GET /summaries/*` reads Mongo `ai_summaries` and never calls a model; a failed or over-budget call keeps the last text.
- Prompts live in `backend/prompts/*.md`; `render` raises `KeyError` on missing or extra placeholders (`prompts/__init__.py::render`).
- Ingest has a single leader; reactions are idempotent through claim stamps on `news_items`, so a restart never double alerts.
- Every user-owned record carries `user_id` (`trade_plans`, `chat_actions`, `plan_scorecards`).
- Token-checked locks: the daily pass releases `scheduler:daily_lock` only if it still holds the token; `backend/locks.py::renew/release` likewise.

## Endpoints

All behind `get_current_user` (router-level dependency in `backend/server.py`, prefix `settings.API_PREFIX`); none is admin-only.

| Method path | handler | response keys the frontend reads |
|---|---|---|
| GET `/news/feed?scope&mine&material&before&limit<=100` | `routers/news.py::news_feed` | `items[]`: `id,title,url,source,published_at,scope,themes,event,impacts,symbols,material,status` (`frontend/src/utils/api.js::newsFeed`) |
| GET `/news/symbols?symbols=A,B` (<=100) | `news.py::symbol_news` | `symbols{SYM:{sentiment,headline,url,direction,impact,material,published_at}}` (72h window) |
| GET `/news/symbol/{symbol}?days=180` (1-365) | `news.py::symbol_history` | `{symbol, items[{id,title,url,published_at,direction,impact,material}]}`: SCORED items whose `impacts.target` or `symbols` name it, newest first, max 500; direction/impact are that symbol's own impact, `material` = own impact >= 6 (uses the `(impacts.target,published_at)` and `(symbols,published_at)` indexes) |
| GET `/plan/today` | `routers/plan.py::plan_today` | `plan, versions[{version,at,trigger,risk_multiplier,skip_day,rationale}], scorecards[{date,a,b,plan_versions}], weeks_beating` (`frontend/src/utils/plan.js`) |
| GET `/chat/actions/pending` | `chat_actions.py::pending_actions` | `[{id,kind,summary,venue,needs_second_tap,expires_at}]` |
| POST `/chat/actions/{id}/confirm` body `{confirm_token}` | `chat_actions.py::confirm_action` | `status` CONFIRMED / NEEDS_SECOND_TAP (+ `confirm_token`, `expires_in`), `result`; 409 `detail` on `ActionRefused`; `TokenRefused` -> its status (409/403) with body `{detail: text, code: confirm_*}` |
| POST `/chat/actions/{id}/cancel` | `chat_actions.py::cancel_action` | `status:"CANCELLED"`; 409 "Nothing to cancel." |
| WS actions `chat`, `analyze`, `quick_analyze` (outside globs: `backend/ws/routes.py`) | `_stream_chat`, `_stream_analysis`, `_stream_quick_analysis` | `chat:{req_id}` events `thinking, content, action, suggestions, done, error` (data `{text}` except action/suggestions); `analysis:{req_id}` `started, report, error`; `quick_analysis:{req_id}` `report, error` |
| GET `/market/brief` | `routers/market_data.py::get_market_brief` (stored brief via `market.py::latest_brief`, no LLM, 404 when none) | `text, as_of, regime` |
| GET `/research/{symbol}/note` | `routers/market_data.py::get_cached_note` (only the cached `analyst:{SYM}` note, no LLM, 404 when none; `as_of` derived from the key's TTL) | `summary, thesis, as_of` |
| GET `/market/index/{ticker}/analysis` (outside globs) | `routers/market_data.py::get_index_analysis` | `analysis, session, headlines, generated_at, cached` |

## Gotchas and known issues

- `bars.py::read` / `::prev_closes` sort `(symbol, date)` (the unique index). A global `date` sort over the 2009+ table is an in-memory sort Atlas refuses past 32 MB; until 2026-10-19 it made `picks.load` fail every pass.

- Past fixes here (git log): `0033585` bounded shutdown (loops outlived cancel on 2026-10-15, worker idle for days); `779a419` ingest exits hard on lost leadership (asyncio.run waited on a blocked to_thread); `34a66f9` broker daily bars missing the latest session are topped up from Yahoo; `4370881` full bar passes backfill from 2009 in 50-ticker chunks; `6a38654` prune rewrites/unfollowed/other-script items before scoring; `1800a7a` zoneless RSS dates are IST and never future; `fbf8a27` a Google company search tags only stories naming the company; `ffd9d9a` dead Moneycontrol feeds replaced; `2be007e` brief hourly only when regime moved or material news; `2c2aba4` plan only with a live feed, skip paused strategies, 2 revisions and 2 tool rounds; `a9a2b09` replay reads `trading_runs` (scorecards had always been empty); `e47b400` content-block replies joined into one string; `f21e249` no weekend daily pass, catch-up off the tick, failed AI text not kept; `f8863de` 09:20 catches up the whole missed pass; `0fc3dad` "held" means real holdings; `b3e7b3c` autopilot trades only proven themes; `8b3c906` verdict gate in chat and LLM limits on HTTP analyze; `c1e9d76` one index explanation per index in Redis; `9af6ed6` Lab switch.
- News stall alert (`news.py::stall_alert`, end of each `process_loop` pass, only `near_session` with feature `news` on): `lag` (retried rows excluded) flags `triage` (oldest fresh NEW waited > 30 min), `backlog` (> 500 fresh NEW), `score` (an item waited > 30 min and nothing scored in 30 min); each sends the admins a Telegram via `data_quality._send_admins` at most once per 2h (`news:stall_alert:*` SET NX EX). `/system/status` `news.lag` shows the same numbers and `stalls`. It cannot fire if the ingest worker itself is down: the heartbeat check in `data_quality.live` covers that.
- `/health` and `analysis.py::from_layer` use ingest heartbeats: a missing heartbeat means no clean pass within `max(300, 2*interval)`; `news_process` older than 15 min makes the analyst fall back to on-demand Google News scoring.
- `reactor._claim` only sees items scored in the last 30 min and published in the last 6h (deliberate: stale news is not urgent). If the ingest worker is down longer, alerts, news scans, shadow exits, outcome snapshots and plan triggers for those items are lost for good. Stamps are written before the work; a failing `_deliver` releases that alert's hourly `ALERT_KEY` throttle.
- `sentiment:` is written only for followed names with some company, sector or market news; a name with none has no key ("no data"), not 0.0. Consumers that read `None` as neutral (`score_intent`) are unchanged.
- `analyst_verdict:{SYM}` has two writers (`news.aggregate` every 10 min for symbols with a 14-day company item; `refresh_analyst_verdict` in the 16:00 pass for `FO_UNDERLYINGS`); last write wins, same 25h TTL (left as is: both derive from the same layer sentiment). `AnalystAgent._store` (symbol not followed, or ingest layer stale) no longer overwrites a `sentiment:{SYM}` that still has more than 4h to live.
- `market_cache` keys share the `market:` namespace with `market:regime|brief|flows|sentiment`; current callers use indices/movers/global/news only, so a new SWR key must not reuse those four names. Empty fetches are never cached; `_local` fallback is per process.
- `scheduler.py::run_daily_jobs` takes `pass_day` (from `_run_locked`): a Monday catch-up for a missed Friday still runs Friday's weekly mirrors and builder `start_if_due`. `send_postclose` still uses the real `now`.
- Direct collection reads inside prompt builders (`plan/builder.py::_headlines`, `::_held_and_watched`, `::_context`; `datalayer/analysis.py::from_layer`) bypass the "AI reads through `ai/facts`" rule in `.claude/CLAUDE.md`. The JSON repair message in `ai/runner.py` is still inline; the final-turn prompt is `prompts/final_turn.md`.
- `llm.py::MultiKeyChain.astream_events` falls back to the next key only before the first event; a mid-stream failure re-raises.
- `chat/agent.py::TOOL_LABELS` covers every chat tool (`tests/test_chat_agent.py` checks); add a label when adding a tool. `stream_chat` shows a generic "try again in a minute" on failure (the exception is only logged).
- `ai/facts/user.py::portfolio` re-scopes with `scorecard_for(..., verdicts=account != "ai")`, so the AI account's facts carry no review verdicts.
- `plan/store.py::save` sets `version = last + 1` with no unique index on `(user_id,date,version)` (index creation is in `server.py`, not done); safe only because builds hold `plan:build:` and revisions run on the single ingest leader. A retry-on-duplicate needs that index.
- (fixed) duplicate `gross_margins` in `CompanyInfo` and the dead branch in `calculate_position_size` are gone.
- `TrendDetector.detect_trend` returns CHOPPY under 200 rows, so quick analysis shows "Sideways" for short histories; `returns["1y"]` needs >=240 bars.
- Handbook `jobs-and-ops.md` now matches the code (guardrail monitor 9:15-15:35 `monitor.py::in_session`, heartbeat 30 s/90 s TTL, `corp_events` listed, `/health` shape).
- LLM failures are strings, not exceptions: compare with `LLM_DISABLED` and `startswith("Error generating response")` (done in `market.py::brief`, `plan/builder.py`, `plan/revise.py`, `index_move.py`, `analyst/agent.py::_split_report`, `chat/agent.py::suggest_followups`). New call sites must do the same.
- `propose_strategy` tool description embeds `builder/draft.py::_vocabulary()` at call time; changing that changes the tool schema.

## Tests

`backend/tests/`: `test_summaries.py` (every AI summary: facts, once per period, failure fallback, user scope), `test_datalayer_worker.py` (leader, loops, shutdown), `test_datalayer_prices.py`, `test_datalayer_news.py`, `test_datalayer_reactor.py`, `test_datalayer_outcomes.py`, `test_datalayer_market.py` (regime, brief gating), `test_datalayer_bars.py`, `test_datalayer_catalysts.py`, `test_market_news.py` (`/news/market`, `/news/feed`, `/news/symbols`), `test_analyst_agent.py`, `test_ai_facts_market.py`, `test_ai_facts_user.py`, `test_ai_runner.py`, `test_ai_grounding.py`, `test_ai_sentiment.py`, `test_ai_analyst_verdict.py`, `test_chat_agent.py`, `test_chat_actions.py`, `test_chat_orders.py`, `test_chat_tools.py`, `test_chat_query_tool.py`, `test_chat_context.py`, `test_plan_builder.py`, `test_plan_builder_tools.py`, `test_plan_validate.py`, `test_plan_store.py`, `test_plan_gate.py`, `test_plan_runner.py`, `test_plan_revise.py`, `test_plan_revise_tools.py`, `test_plan_replay.py`, `test_plan_notify.py`, `test_plan_router.py`, `test_research_quick.py`, `test_stock_flags.py`, `test_research_graph_demoted.py`, `test_index_move.py`, `test_llm.py`, `test_llm_tiers.py`, `test_llm_call_tiers.py` (pins every call site's tier and feature), `test_llm_content_blocks.py`, `test_model_catalog.py`, `test_market_cache.py`, `test_prompts.py`, `test_scheduler.py` (IST timing, per-user isolation, lock, catch-up day), `test_lab_switch.py` (the seven Lab gates), `test_app_settings.py`, `test_autorun.py`, `test_indicators.py`, `test_stock_info_logo.py`, `test_system_jobs.py`.
