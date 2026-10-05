# News Across the App, Plan Card, Library Page and Telegram Plan Summaries (Phase 15.4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every page that lists stocks shows what the news says about them, the AI tab shows today's game plan and how it is scoring, a Library page shows the strategy cards, the journal learns from news at entry, and Telegram carries the plan.

**Architecture:** One backend summary endpoint (`GET /news/symbols`) feeds a shared `NewsChip` used by Holdings, Watchlist, Scanner and Decisions. `GET /plan/today` feeds a `PlanCard` on AI → Activity. A new `/practice/library` page reads the existing `GET /strategies/library`. Journal trips get a news snapshot attached at read time before `build_insights`. `backend/plan/notify.py` sends plan summaries through the existing per-user Telegram channel. No new LLM calls anywhere.

**Tech Stack:** FastAPI + Motor (backend, pytest + mongomock), React 19 + Vite + Tailwind tokens from `DESIGN.md` (frontend), `node --test` for pure frontend utils, `npm run build` as the frontend build check.

**Spec:** `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md` (section 4)

## Global Constraints

- Read-only consumers of existing datalayer data (`sentiment:{SYM}`, `news_items`); **no new LLM calls**.
- UI follows `DESIGN.md` and the existing doc components (`components/doc/Doc.jsx` `Sheet`, `Ruling`); colours only via CSS tokens (`var(--gain)`, `var(--loss)`, `var(--ink-soft)`, `var(--rule)`); 44 px tap targets (`min-h-11`); works at phone width.
- Every frontend change passes `cd frontend && npm run build`; pure utils get `node --test src/utils/<name>.test.js`.
- Backend tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest backend/tests -q -p no:cacheprovider` (2 known kill-switch tests fail between 00:00 and 05:30 IST only).
- Deploy: direct. Backend rebuild in the deploy clone; the frontend deploys through Vercel's git integration on push (`[skip ci]` does not stop it).

## Decisions this plan makes

- **Decisions inbox** shows the stock's news at read time through the same chip, not a snapshot stored on each proposal (one source, no schema change).
- **Journal news** is attached at read time (`attach_news` looks back 24 h before each trip's open), not stored on trades — journal trips come from broker sync, not the engine ledger. News history starts 2026-10-05, so the two new findings appear once enough trips exist.
- **Settings keeps its promotion table** (it holds the live toggles); the Library page links to it rather than replacing it.
- **Telegram** gets a message for every non-fallback version (pre-open and each revision), never for fallback plans.

## Review Focus

1. `GET /news/symbols` with 0 symbols, >100 symbols, or symbols with no news → `{}` entries absent, never an error; cap 100. Pinned in Task 1.
2. A chip for a symbol with sentiment but no headline (or headline but no sentiment) renders without "undefined"/"NaN". Pinned in Task 2 (util test).
3. `/plan/today` for a user with no plan today → `{"plan": null, ...}`, page shows "No plan today" instead of crashing. Pinned in Tasks 4–5.
4. Telegram not linked → plan saving never fails because of notify. Pinned in Task 7.
5. Journal trips on options/futures symbols → news looked up by underlying, never crashes. Pinned in Task 3.

---

### Task 1: `GET /news/symbols`

**Files:** Modify `backend/components/analyst/news.py`; Test `backend/tests/test_market_news.py` (append).

**Interfaces — Produces:** `GET /news/symbols?symbols=TCS,INFY` → `{"symbols": {SYM: {"sentiment": float|None, "headline": str|None, "direction": float|None, "impact": float|None, "material": bool, "published_at": iso|None, "url": str|None}}}`. Symbols upper-cased, `.NS` stripped, ≤ 100 (extra ignored). Headline = most recent SCORED item in the last 72 h with a `type=="symbol"` impact on that symbol (its title/url and that impact's direction/impact/material flag). A symbol with neither sentiment nor headline is omitted.

- [ ] Step 1: failing tests `test_symbol_news_summarises_sentiment_and_latest_headline`, `test_symbol_news_omits_quiet_names_and_caps_the_list` (101 symbols → no error; quiet name absent).
- [ ] Step 2: run — FAIL. Step 3: implement. Step 4: run — PASS.
- [ ] Step 5: commit `feat(news): per-symbol news summary for list pages [skip ci]`

---

### Task 2: `NewsChip` on Holdings, Watchlist, Scanner and Decisions

**Files:** Create `frontend/src/utils/news.js` + `news.test.js`, `frontend/src/hooks/useSymbolNews.js`, `frontend/src/components/common/NewsChip.jsx`. Modify `frontend/src/utils/api.js` (`newsSymbols: (symbols) => '/news/symbols?symbols=' + …`), `MyPortfolio.jsx` (holding rows), `Watchlist.jsx`, `ScannerPage.jsx` (+ "Has news (24h)" filter toggle), `Decisions.jsx` / `components/decisions/WaitingCards.jsx` (proposal cards).

**Interfaces — Produces (`news.js`):**
- `tone(entry) -> 'pos' | 'neg' | 'flat' | null` (sentiment ≥ 0.2 pos, ≤ −0.2 neg, else flat; null when no sentiment and no direction; falls back to headline direction)
- `chipLabel(entry) -> string` ("News +0.4", "News −0.6", "News" when no number)
- `hasRecentNews(entry, hours=24, now=Date.now()) -> bool`
- `sortByNewsRisk(rows, newsBySymbol) -> rows` (rows with a material negative headline first, original order otherwise)
- `useSymbolNews(symbols: string[]) -> {news: object, loading: bool}` (one request per distinct sorted symbol list; errors → `{}`)
- `<NewsChip entry={...} />`: small token-coloured label + headline (truncated, links to `url`, `title` attribute holds the full headline); renders nothing for `undefined`.

- [ ] Step 1: failing `node --test src/utils/news.test.js` — tone thresholds, label never contains "NaN"/"undefined" for partial entries, `hasRecentNews` window, `sortByNewsRisk` stability.
- [ ] Step 2: run — FAIL. Step 3: implement util, hook, chip, wire the four pages (holdings sorted with `sortByNewsRisk`). Step 4: tests PASS and `npm run build` succeeds.
- [ ] Step 5: commit `feat(ui): news chips on holdings, watchlist, scanner and decisions [skip ci]`

---

### Task 3: Journal news at entry and two findings

**Files:** Create `backend/journal/news.py`; modify `backend/journal/insights.py`, `backend/routers/journal.py:83`, `backend/chat/tools.py:135`; Test `backend/tests/test_journal_news.py`.

**Interfaces — Produces:**
- `async def attach_news(db, trips: list[dict]) -> list[dict]` — sets `trip["news"] = {"direction", "impact", "minutes_before"}` from the strongest `type=="symbol"` impact on `trip["underlying"] or trip["symbol"]` in SCORED items published in `[opened_at − 24h, opened_at]`, else `None`. One Mongo query for all trips.
- In `build_insights`: `"against_news"` finding — trips whose `news.impact ≥ MATERIALITY_THRESHOLD (6)` and `news.direction` opposes the trip direction (`LONG` vs negative, `SHORT` vs positive), title "Traded against strong news"; `"chasing_news"` — trips with `news.minutes_before ≤ 15` and impact ≥ 6, title "Entered within 15 minutes of big news". Both need ≥ `MIN_TRIPS` trips; use `_finding` like the others.

- [ ] Step 1: failing tests `test_attach_news_uses_the_underlying_and_the_24h_window`, `test_against_news_and_chasing_news_findings`, `test_no_news_no_finding`.
- [ ] Step 2–4: FAIL → implement (+ wire both callers) → PASS.
- [ ] Step 5: commit `feat(journal): news at entry and what it says about your trades [skip ci]`

---

### Task 4: `GET /plan/today`

**Files:** Create `backend/routers/plan.py` (register in `backend/server.py` like the other routers); Test `backend/tests/test_plan_router.py`.

**Interfaces — Produces:** `GET /plan/today` → `{"plan": current Redis plan or null, "versions": [{"version","at","trigger","risk_multiplier","skip_day","rationale"}], "scorecards": last 10 `plan_scorecards` docs (date, a, b) newest first, "weeks_beating": int}`.

- [ ] Step 1: failing tests `test_plan_today_returns_plan_versions_and_scorecards`, `test_plan_today_without_a_plan`.
- [ ] Step 2–4: FAIL → implement → PASS.
- [ ] Step 5: commit `feat(plan): today's plan, its revisions and scorecard over the API [skip ci]`

---

### Task 5: Today's plan card on AI → Activity

**Files:** Create `frontend/src/components/plan/PlanCard.jsx`, `frontend/src/utils/plan.js` + `plan.test.js`; modify `frontend/src/pages/AiActivity.jsx`, `frontend/src/utils/api.js` (`planToday: '/plan/today'`).

**Interfaces — Produces (`plan.js`):** `triggerLabel(trigger) -> string` ("Pre-open plan", "Regime change", "Event passed", "News", "Fallback (AI unavailable)"); `scoreLine(cards) -> string` ("Plan ₹+1,240 vs no plan ₹+310 over 5 days" — sums `a.net` and `b.net`, Indian number format, sign shown); `allowSummary(plan) -> [{symbol, strategies}]`.

Card content: rationale lines; risk multiplier ("Risk 0.85×") and max positions; allowed pairs (symbol → strategy chips); added names; revision timeline (time, `triggerLabel`, first rationale line); score line + "Plan ahead N weeks in a row" when `weeks_beating > 0`; "No plan today" otherwise.

- [ ] Step 1: failing `node --test src/utils/plan.test.js`.
- [ ] Step 2–4: FAIL → implement card + page wiring → tests PASS, `npm run build` OK.
- [ ] Step 5: commit `feat(ui): today's game plan on AI activity [skip ci]`

---

### Task 6: Strategy Library page

**Files:** Create `frontend/src/pages/Library.jsx`, `frontend/src/utils/library.js` + `library.test.js`; modify `frontend/src/App.jsx` (route `/practice/library`), `frontend/src/components/layout/sections.js` (Practice tab "Library"), `frontend/src/utils/api.js` (`strategyLibrary: (mode) => …`).

**Interfaces — Produces (`library.js`):** `statusOf(card) -> 'live-ready' | 'paper' | 'paused' | 'untested'` (paused if `learned.paused`; untested if no backtest; live-ready if backtest passed and paper passed; else paper); `recordLine(card) -> string` ("12 trades · win 58% · net ₹+3,200" or "No paper trades yet").

Page: INTRADAY / LONGTERM toggle; one card per strategy: name, style, regimes, needs, best/avoid sentences, `statusOf` badge, `recordLine`, link "Live switches in Settings" to `/settings`.

- [ ] Step 1: failing `node --test src/utils/library.test.js`.
- [ ] Step 2–4: FAIL → implement → PASS + `npm run build`.
- [ ] Step 5: commit `feat(ui): strategy library page [skip ci]`

---

### Task 7: Telegram plan summaries

**Files:** Create `backend/plan/notify.py`; modify `backend/plan/builder.py` (after a non-fallback save), `backend/plan/revise.py` (after a revision save); Test `backend/tests/test_plan_notify.py`.

**Interfaces — Produces:** `def plan_text(doc: dict) -> str` — pre-open: "📋 Today's plan" + rationale lines + "Risk {m}× · up to {n} positions" + allowed symbols (≤ 8, "+k more") + adds; revision: "🔁 Plan updated ({triggerLabel})" + rationale + exits ("Exit TCS: guidance cut"). `async def notify_plan(db, user_id, doc) -> bool` — `GuardrailStore(db).telegram_channel(user_id)`; None → False; else `telegram.send_buttons(chat_id, text, STOP_BUTTON, token)` (reuse `autopilot.service.STOP_BUTTON`); any exception logged, returns False.

- [ ] Step 1: failing tests `test_pre_open_text`, `test_revision_text_lists_exits`, `test_notify_without_telegram_is_a_quiet_false`, `test_builder_save_survives_a_failing_notify`.
- [ ] Step 2–4: FAIL → implement → PASS (full suite).
- [ ] Step 5: commit `feat(plan): game plan summaries on Telegram [skip ci]`

---

### Task 8: Docs, deploy, verify

- [ ] ROADMAP (15.4 done, Phase 15 done), ARCHITECTURE (surfacing), spec "As built (15.4)" with this plan's decisions.
- [ ] Full backend suite; `npm run build`.
- [ ] Commit + push; backend rebuild in deploy clone; confirm the Vercel production deployment for the push reaches READY.
- [ ] Verify on prod: `GET /news/symbols?symbols=HDFCBANK,TCS` and `GET /plan/today` respond 200 for a real user (via `docker exec` + the app's TestClient pattern, or curl with a session token).
