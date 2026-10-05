# NeoTrade: a shared market, macro & news data layer

## Context

Today every consumer fetches and analyses on its own call path. The analysis covers single companies only.

- **News.** Only per-company news is fetched, and only on a cache miss. The fetchers are `AnalystAgent` (`backend/components/analyst/agent.py`), portfolio health, chat `fetch_news_tool` (uncached), and index_move (per-worker dict).
  - Global and macro events reach the AI only as three Google "market today" queries, shown as raw headlines and never scored (`news.py:38`). Examples: Fed, crude, rupee, geopolitics, RBI, FII flows, US/Asia markets.
  - Sentiment `sentiment:{sym}` (4h TTL) fills only at the 16:00 pass or when a user clicks. So the 09:15–15:30 engine mostly scores intents with AI = neutral.
- **Quotes.** `marks.mark_prices` has no cache. The ws pump (both workers, every 15s), positions, pnl, autopilot, exits, paper sweep and approvals all call yfinance separately.
- **Bars and fundamentals.** These sit in per-worker caches: `CachedHistory`, `CachedFundamentals`, `_NIFTY*`, `_quote_cache`.
- **Bugs to fix on the way.**
  - Per-symbol news uses the US Google query, because bare "RELIANCE" fails the `.NS` check at `news.py:107`.
  - Finnhub is sent NSE symbols it doesn't cover.
  - There is no lock on an analyst cache miss.

**Goal.** One data layer continuously collects and stores **every news item that can move Indian markets**:

- company news
- sector news
- Indian market, macro and policy news
- global and geopolitical events
- the hard numbers behind them (crude, USDINR, US yields, DXY, VIX, GIFT Nifty, FII/DII flows, economic calendar)

The layer scores each item for *what it affects* (market / sectors / symbols) and keeps the latest quotes, bars and fundamentals. The whole app reads from it. New items are processed within 1–2 minutes. They can trigger sentiment updates, Telegram/WS alerts, new suggestions and autopilot reactions. Every stored item also records what prices did afterwards, so the AI can learn which kinds of news actually matter.

**User decisions.**
- Triggers: all four.
- Universe: Nifty 200 + held + watched.
- Latency: 1–2 min, by polling.
- Runtime: a separate `ingest` container.
- Scope: all market-relevant news, global included.

**Invariants kept.**
- AI cap 30% and rule floor 0.45 through `composite.py`.
- News never sizes a trade or invents conviction. It only feeds the one `ai_score` input, refreshes `analyst_verdict:`, re-runs existing strategies, or *tightens* risk limits.
- Autopilot only on the `ai` account, after `fence.check`.
- Per-user data carries `user_id`.

## Architecture

```
            ┌──────────────── ingest container (same image, 1 replica, leader lock) ───────────────┐
sources ──► │ quote_loop 15s   macro_loop 60s   news_poll 60s ─► news_items ─► triage (fast LLM)      │
yf, RSS,    │ bars_loop EOD    calendar daily                          │ relevant ─► scorer (deep LLM)│
NSE, RBI,   │ fundamentals daily                                       ▼                              │
GDELT, FF   │        aggregator: symbol / sector / market sentiment, market_brief (15 min)            │
calendar    │        material? ─► XADD news:events ─► reactor: alerts / scan / autopilot / regime     │
            │        outcomes loop: price reaction at +1h/+1d/+5d per item                            │
            └──────────────────────────────────────┬───────────────────────────────────────────────────┘
      Redis: quote:*, macro:*, sentiment:*, sector_sentiment:*, market:regime, analyst_verdict:*, ws:events
      Mongo: news_items, news_outcomes, macro_series, econ_calendar, market_briefs, daily_bars, fundamentals
                                                   ▼
                  API workers (2): read-only consumers + on-demand fallback
```

The new package `backend/datalayer/` has one entrypoint, `python -m backend.datalayer.worker`, which runs one asyncio task per loop.

## What gets collected

### News sources (`datalayer/news_sources.py`, all polled concurrently every 60s unless noted)

| Scope | Sources |
|---|---|
| Company | NSE corporate announcements JSON (results, orders, pledges, board meetings; needs nseindia.com cookie warm-up; on failure log and skip). Per-symbol Google News `"{company name}" share news`, IN/en-IN: held/watched every 5 min, rest of Nifty 200 round-robin ~10/min. |
| Sector | Google News per sector query (`"Indian banking sector"`, IT, pharma, auto, metals, FMCG, energy, realty…; ~12 queries every 10 min) |
| India market / macro / policy | ET Markets, Moneycontrol, LiveMint RSS; RBI press releases RSS; SEBI RSS; PIB (government) RSS; existing `MARKET_QUERIES` with `when:1h` |
| Global / geopolitics | Google News Business + World topic RSS; CNBC world/markets RSS; GDELT DOC API (15-min updates, filtered to themes: conflict, sanctions, central banks, oil, trade). Keep the source list in `configs/news_sources.yaml`, so adding a feed needs no code change |

Finnhub is dropped for NSE symbols because it has no coverage there.

### Hard numbers (`datalayer/macro.py`)

| Data | Where | Cadence |
|---|---|---|
| Crude (Brent/WTI), gold, USDINR, DXY, US 10Y, S&P/Nasdaq futures, Nikkei/Hang Seng, India VIX, GIFT Nifty proxy | yf batch download → Redis `macro:{KEY}` (`{value, change_pct, at}`, EX 5 min) + Mongo `macro_series` (1-min points in session, daily close kept forever) | 60s |
| FII/DII cash flows | NSE `fiidiiTradeReact` JSON → `macro_series` | daily after 18:00 IST |
| Economic calendar (Fed, CPI, RBI MPC, US jobs, India GDP/CPI…) | ForexFactory weekly JSON + RBI MPC dates → Mongo `econ_calendar` `{at, country, event, impact, forecast, previous, actual}` | daily, plus every 5 min around high-impact events to capture `actual` |

The pages and chat already show some of these (`/market/global`, `/market/indices`). After this change they read from the layer.

## Stores

| Data | Where | Shape / TTL |
|---|---|---|
| News items | Mongo `news_items` | `_id`=sha1(normalised title key, reusing `news._title_key`). Fields: `title, url, source, published_at` (aware UTC), `content, fetched_at`, `scope` (COMPANY/SECTOR/MARKET/MACRO/GLOBAL), `themes[]` (rates, crude, fx, geopolitics, earnings, regulation, flows, …), `region` (IN/US/CN/GLOBAL…), `impacts[]` = `{target_type: market|sector|symbol, target, direction -1..1, impact 0..10, horizon: intraday|days|weeks}`, `relevant, material, triaged_at, scored_at`. Indexes: `impacts.target+published_at`, `scope+published_at`, `scored_at`. Retention: relevant items kept **2 years** (learning data); irrelevant ones get a TTL of 7 days |
| News outcomes | Mongo `news_outcomes` | `{item_id, target, ret_1h, ret_1d, ret_5d, bench_ret_*}`: the target's (symbol, sector index or Nifty) return vs Nifty after the item |
| Symbol sentiment | Redis `sentiment:{SYM}` (same key; readers untouched) | float, EX 24h, see aggregation |
| Sector sentiment | Redis `sector_sentiment:{SECTOR}` | float + top drivers |
| Market regime | Redis `market:regime` | `{score -1..1, label risk_on/neutral/risk_off, drivers[], at}` |
| Market brief | Mongo `market_briefs` + Redis `market:brief` | ≤300-word structured summary of the last 24h: macro, global, sector tilts, upcoming calendar events |
| Analyst verdict / report | Redis `analyst_verdict:{SYM}`, `analyst:{SYM}` (shapes unchanged) | verdict for every universe symbol; report rebuilt lazily |
| Quotes | Redis `quote:{SYM}` | `{ltp, prev_close, at}`, EX 120s |
| Daily bars | Mongo `daily_bars` | unique `(symbol,date)`; 400-day backfill, then appended after 15:45 IST |
| Fundamentals / sector map | Mongo `fundamentals` (reuses `instrument_sectors` data) | daily |
| Heartbeat | Redis `ingest:heartbeat:{loop}` | EX 5 min |

Every record carries `at`/`as_of`. Readers treat stale data as missing.

## News pipeline

1. **Ingest and dedupe.** Each item is inserted with `_id` = title-key hash, so the same story from many sources becomes one doc, with sources and symbols merged. Ingest is idempotent across restarts.
2. **Tagging, a cheap pre-pass** (`datalayer/tagger.py`).
   - An alias map (tradingsymbol + company name minus "Ltd/Limited") is built daily from `instruments`, along with sector keyword lists.
   - Word-boundary regex attaches candidate symbols and sectors.
   - NSE filings arrive pre-tagged.
3. **Triage, fast-tier LLM** (`prompts/triage_news.md`).
   - Headlines go in batches of up to 25 per call.
   - Each headline gets `relevant_to_indian_markets` plus a first `scope` and `themes`.
   - This lets global volume (hundreds of items an hour) through without deep-scoring noise.
   - Irrelevant items are stored with the 7-day TTL.
4. **Scoring, deep-tier LLM** (`prompts/score_news.md` extended into `score_market_news.md`).
   - Relevant items are batched by scope and by symbol.
   - The output is `impacts[]` per item, so one item can hit several targets. Example: "Brent +6% on Gulf strike" gives market −0.3, sector OMCs −0.6, aviation −0.5, upstream oil +0.5.
   - The prompt is given the sector list and the item's candidate symbols, so targets stay inside known entities. The validator drops unknown targets.
   - `_score_news`'s retry/JSON-extraction pattern is extracted from `agent.py` and reused.
   - Budget: `NEWS_LLM_CALLS_PER_MIN` (default 15, in `configs/settings.py`), in priority order:
     1. held
     2. MACRO/GLOBAL material
     3. watched
     4. Nifty 200
     5. rest
   - The backlog stays in Mongo.
5. **Aggregation** (`datalayer/aggregate.py`, runs after each scored batch). Every component uses the existing impact² × 30-day half-life `_weighted_sentiment` over the last 60 days of impacts on that target.
   - `company(SYM)`, `sector(S)` and `market` are each computed this way.
   - `sentiment:{SYM}` = clamp(0.6·company + 0.25·sector(sym's sector) + 0.15·market).
     - When a symbol has no company news, its sector and market still move it, so global events now reach every stock's AI input.
     - This is still the **single** `ai_score` input that `composite.py` caps at 30%. Weights go in settings and are documented in ARCHITECTURE.md. It is not a second conviction formula.
   - `sector_sentiment:*` and `market:regime` are written from the same components. Regime also folds in hard numbers: VIX level/change, crude and USDINR moves, US futures. These are simple z-scored rules in code, not LLM output.
   - `analyst_verdict:{SYM}` is written in the existing `ai/analyst_verdict.py` shape, so `AnalystVerdictStrategy` keeps working unchanged.
6. **Market brief.**
   - When it runs: every 15 min in session, hourly outside it, and immediately after a material MACRO/GLOBAL item.
   - Prompt: `prompts/market_brief.md`, standard tier.
   - Input: top-impact items from the last 24h, macro numbers, and the next 48h of `econ_calendar` high-impact events.
   - Output: `market:brief`.
7. **Materiality.**
   - An item is material when any impact is ≥ 6 (`MATERIALITY_THRESHOLD`, from `strategies/longterm/analyst_verdict.py`).
   - Material items are added with `XADD news:events {item_id, scope, targets}`.
   - It is a Redis Stream with a consumer group, so reactions survive an ingest restart.
   - `ws:events` pub/sub stays for UI fan-out only.
8. **Outcomes, the learning hook** (`datalayer/outcomes.py`).
   - At +1h, +1d and +5d after each material item, the loop records each target's return and Nifty's return into `news_outcomes`, using `quote:`/`daily_bars` (sector targets use the sector index).
   - A weekly job feeds the existing learning loop (`backend/learning/`, `scheduler._learn`). It computes hit rate and average move by `scope × theme × direction`, and writes `news_theme_weights`.
   - The aggregator multiplies each impact by its theme weight, clamped to 0.5–1.5. Themes that historically moved prices count more; noise counts less.
   - This is the "helps AI trade better" loop. It ships after a few weeks of data exist.

## How the AI uses it

| Consumer | Gets |
|---|---|
| Intraday engine + scans (`runner.py:143`, `scan.py`) | fresher `sentiment:{SYM}` that now includes sector + market. No code change; `get_cached_sentiment` is unchanged |
| Research report (`prompts/research_report.md`) | adds `{{market_brief}}` + the sector's top drivers |
| Chat (`backend/chat/context.py` day snapshot) | adds `market:brief`, `market:regime`, today's calendar. New read tools: `search_news(query, scope, target, since)` over `news_items`, `get_macro(keys)`, `get_calendar(days)`. Replaces the uncached `fetch_news_tool` |
| Index explanation (`research/index_move.py`) | reads `news_items` (MARKET/MACRO/GLOBAL) + `macro:*` instead of its own fetches |
| Portfolio review / health | sector + market sentiment per holding; headlines from the store |
| Autopilot fence (`autopilot/fence.py`) | new rule: `market:regime` = risk_off (score ≤ −0.5), or a high-impact calendar event within 30 min, **halves the per-trade cap and blocks new entries**. Exits are never blocked. This only tightens; it never loosens |

## Reactions (`datalayer/reactor.py`, consumer group on `news:events`)

| Reaction | What | Guards |
|---|---|---|
| Score update | done by the aggregator | — |
| Alert | `suggestions/notify.notify` + `hub.publish` on topic `news:{SYM}` / `news:market`. Company/sector items go to users holding or watching an affected symbol (sector via the sector map). MACRO/GLOBAL items with market impact ≥ 7 go to all users with open positions | pref `news_alerts`: `held` (default), `held+watched`, `all`, `off`. One alert per user+target per hour (`SET NX`) |
| New suggestion | `scan_universe(db, user_id, universe=affected ∩ user universe, source="news")`, the same strategies → `Intent` → `composite.py` path. Change `scan.py:107` to load verdicts for the scanned universe, not just `FO_UNDERLYINGS` | `has_pending` dedupe; at most 1 news-scan per user+symbol a day; a sector/macro event re-scans at most 20 symbols per user |
| Autopilot entry | the new suggestion goes through `engine/autorun._autopilot_proposals` → `autopilot.service.submit` → `fence.check` (including the regime rule) | new pref `autopilot_news` (default **off**); `ai` account only; paper unless `autopilot_live`; kill switch; ≤3 news-triggered actions a day |
| Autopilot exit | material negative impact (≥ 8, direction ≤ −0.5) on an AI-account long, direct or via its sector → `submit` SELL `source="news"`, with a Telegram stop button | same pref and caps; shadow mode (log only) for 2 weeks before enabling |

Before Phase 5 ships, record the autopilot news trigger and the regime fence rule as an extension of the 2026-10-04 exception, in `docs/superpowers/specs/` and in the `.claude/CLAUDE.md` invariant.

## Migrating consumers (read from the layer, fall back on a miss)

- **`marks.mark_prices`.**
  - Reads `quote:{SYM}` first. Only missed or stale symbols are fetched, with write-through at a 30s TTL. That fixes the pump, positions, pnl, autopilot, exits and paper sweep in one place.
  - Real-money confirm paths (`approve-live`, chat confirm, autopilot `submit`) accept only quotes ≤ 20s old. Older than that, they fetch live.
- **`AnalystAgent.analyze`.**
  - For universe symbols it is built from `news_items` + aggregates. `research_report.md` is regenerated only when someone requests it and newer scored news exists, under a Redis lock.
  - Non-universe symbols keep today's fetch path, with the region bug fixed.
- **`/news/market`, `/market/global`, `/market/indices`** read the store.
- **Scan, `/scanner`, `research/quick.py`, portfolio closes, the NIFTY series** go through a new `StoreHistoryProvider` (implements `MarketDataProvider.history`, falls back to yfinance). Afterwards `CachedHistory`, `CachedFundamentals` and the `_NIFTY*` dicts are deleted.
- **Dead legacy routes are deleted:** `POST /news/fetch`, `/news/sentiment`, `/events/classify` (`server.py:191-193`), along with their modules and prompts if nothing else uses them.
- **Frontend:**
  - a News page (filters: scope, theme, my holdings; live via WS)
  - a market-regime + brief card on Today
  - alert toasts
  - Settings toggles (`news_alerts`, `autopilot_news`)

## Infra

- **Compose service.** Add `ingest` to `docker-compose.yml`:
  - same `build: ./backend`
  - `command: python -m backend.datalayer.worker`
  - same env, no ports, `restart: unless-stopped`
  - Before editing, check `.github/workflows/deploy-backend.yml` and the shared `ci-workflows` (`/home/ubuntu/docs/host/push-to-deploy.md`), so the deploy also brings `ingest` up.
- **Lock helper.** Extract the token-checked lock from `scheduler.py:141-167` into `backend/locks.py`. Ingest holds `ingest:leader`.
- **Health.** `/health` reports heartbeat ages. The guardrail monitor sends the admin a Telegram when quotes are older than 2 min or news older than 10 min in session. If ingest is down, cache misses fall back to direct fetch automatically.
- **Cost.**
  - Triage: about 1 fast call per 25 headlines.
  - Deep scoring: capped by `NEWS_LLM_CALLS_PER_MIN`; expect about 600–1,000 deep calls a day.
  - Market brief: about 40 standard calls a day.
  - Mongo: news items are ~2 KB each. At a few thousand relevant items a day, that is ~1–2 GB over 2 years. Check the Atlas tier, or trim `content` after 90 days.

## Phases (each shippable alone, in order)

| # | Ships | Done when |
|---|---|---|
| 0 | `backend/locks.py`, worker skeleton + leader lock + heartbeat, `ingest` service, `/health` staleness | container runs; a second instance waits |
| 1 | quote_loop + macro_loop (`macro:*`, `macro_series`) + `mark_prices` read-through + ≤20s confirm rule | API yfinance call count drops; `/market/global` served from the store |
| 2 | all news sources, tagger, triage, scorer with `impacts[]`, aggregator (symbol/sector/market), `analyst_verdict:` for the universe; `AnalystAgent` reads the store; region bug fixed; dead routes removed | in session, a new global/macro headline is stored, triaged and scored within 2 min; `sentiment:` populated for most of the Nifty 200 |
| 3 | econ calendar, FII/DII, market regime, market brief; chat tools + context, research report and index_move use them | chat answers "what's moving markets today" from the store; the brief refreshes on a material macro item |
| 4 | `news:events` stream + reactor alerts + frontend News page / regime card / toasts | a material item on a held symbol (or a market-wide shock) reaches Telegram within 2 min, once |
| 5 | reactor → targeted `scan_universe`; verdicts for the scanned universe | a material item produces a PENDING `source="news"` suggestion with normal `{rule, ai, final}` |
| 6 | `autopilot_news` + regime fence rule; entry live on paper; exit in shadow mode, then on | paper fills tagged `source=news`; regime and calendar block tested; shadow log reviewed |
| 7 | `news_outcomes` + weekly theme weights into the learning loop | the weights table populates after ≥ 3 weeks; the aggregator applies the clamped weights |
| 8 | `daily_bars` + `fundamentals` stores; migrate scan/scanner/quick/portfolio; delete per-worker caches | the scan makes zero yfinance history calls on a warm store |
| later | broker ticks into `quote:` (one market-data session; check broker ToS on sharing across users) | — |

## Critical files

- **New:**
  - `backend/datalayer/{worker,quotes,macro,calendar,news_sources,tagger,triage,scorer,aggregate,brief,reactor,outcomes,bars,fundamentals,store}.py`
  - `backend/locks.py`
  - `backend/configs/news_sources.yaml`
  - `backend/prompts/{triage_news,score_market_news,market_brief}.md`
  - `backend/tests/test_datalayer_*.py`
- **Modified:**
  - `backend/marks.py`
  - `backend/components/analyst/{agent,news}.py`
  - `backend/suggestions/scan.py`
  - `backend/chat/{context,tools}.py`
  - `backend/agents/tools.py`
  - `backend/research/index_move.py`
  - `backend/portfolio/{health,service}.py`
  - `backend/autopilot/fence.py`
  - `backend/routers/{suggestions,market_data}.py`
  - `backend/prefs.py`
  - `backend/configs/settings.py`
  - `backend/server.py`
  - `docker-compose.yml`
  - the frontend News page, Today card and Settings
- **Reused:**
  - `_title_key`, `fetch_google_news`, `MARKET_QUERIES`
  - `_score_news` pattern, `_weighted_sentiment`
  - `get_cached_sentiment`, the `analyst_verdict` shape, `AnalystVerdictStrategy`
  - `scan_universe`, `has_pending`, `_autopilot_proposals`, `autopilot.service.submit`, `fence.check`
  - `notify`, `hub.publish`, `broadcast`, `market_cache`
  - `instrument_sectors` data, the `backend/learning/` loop
- **Docs:**
  - `docs/ARCHITECTURE.md`: new datalayer section, the sentiment blend weights, the regime fence rule, §1.9 updated
  - `docs/ROADMAP.md`: Phase 14

## Verification

**Unit tests** (`cd backend && python -m pytest`):
- dedupe across sources
- tagger aliases + sector keywords
- triage drops irrelevant items
- the scorer validator drops unknown targets
- the aggregator blend:
  - a symbol with no company news moves with its sector/market
  - the result is clamped to [−1, 1]
  - `composite.py` cap still holds end to end
- regime rules from macro numbers
- materiality → exactly one stream entry
- reactor routing:
  - alert rate limit and pref levels
  - scan limited to the affected ∩ user universe
  - autopilot only with `autopilot_news` and only on `ai`
  - exit thresholds, daily caps
  - the regime fence blocks entries but never exits
- `mark_prices` hit/miss/stale; confirm paths reject quotes older than 20s
- outcomes math
- `test_no_network_in_strategies` still passes

**Staging on the VM:**
1. Run `docker compose up -d ingest` and tail its logs.
2. Run `redis-cli` checks on `quote:RELIANCE`, `macro:BRENT`, `market:regime`, `market:brief`, and the `sentiment:` key count.
3. Inject a fake material GLOBAL item ("crude +8%"). Confirm:
   - sector and market sentiment shift
   - OMC symbols' `sentiment:` moves
   - holders get a Telegram alert
   - a `source=news` suggestion appears where strategies agree
   - with `autopilot_news` on, a paper autopilot action happens, or the regime fence refuses it

**Live in session:**
- headline-to-score latency log under 2 min
- `/health` heartbeats fresh
- API yfinance call counter down

**Frontend:** `npm run build` + vitest for the News page, regime card and toggles.
