# Practice Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Engine answers "what is it doing now", Book "how is my practice money doing", Strategies "is any strategy good enough" — each once, net of charges.

**Architecture:** Backend `compute_pnl` gains net-of-charges fields. A pure util computes Book's period figures from closed trades. Engine and Book pages are recomposed from existing components; Library becomes Strategies, absorbing readiness, the track record and the learning sheet.

**Tech Stack:** FastAPI + pytest (mongomock); React 19, Vite, recharts, `node:test`.

**Spec:** `docs/superpowers/specs/2026-10-06-practice-redesign-design.md`

## Global Constraints

- Every practice P&L shown is **net of charges** (`realized_pnl − costs`).
- No figure appears on two Practice tabs.
- `PRACTICE_TABS` = Engine `/practice` · Book `/practice/book` · Strategies `/practice/strategies` · Setup `/practice/setup`; `/practice/library` redirects to `/practice/strategies`.
- Existing `compute_pnl` fields keep their meaning (Today page, chat read them).
- Phone first: every tab measures `document.documentElement.scrollWidth == 390` at a 390 px viewport.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; HEAD subject carries `[skip ci]` (direct deploy this session).

## Review Focus

- A closed trade with no `costs` field (older rows) → treated as 0, not NaN (Task 1 test `test_missing_costs_count_as_zero`; Task 2 test case).
- Book period with no closed trades → "No closed trades this period", no empty chart (Task 2 test: empty → `{net: 0, trades: 0, curve: []}`; Task 4 renders the empty line).
- Market closed → unrealised labelled "at last close" (Task 4, from `useMarketStatus`/`market.open` already used by Today).
- Library deep links `/practice/library` and `?book=` on Engine → land on Strategies with the right book (Task 5 redirect keeps the query).
- Promotion endpoint down → strategy rows still list with the record, gate line says "couldn't load" (Task 5, same posture as `StrategyReadiness`).

---

### Task 1: Net of charges in `compute_pnl`

**Files:** Modify `backend/analytics.py::compute_pnl`; Test `backend/tests/test_analytics.py`

**Interfaces — Produces:** response `today` and `month` gain `costs: float`, `net: float` (= realized − costs); new `all_time: {realized, costs, net, trades, wins}` over every closed trade in scope (same venue/mode filters).

- [ ] **Step 1: Failing tests** — `test_net_subtracts_charges_per_period` (two closed trades today: realized 100 costs 5, realized −20 costs 3 → today.net == 72, today.costs == 8, month.net == 72, all_time == {realized: 80, costs: 8, net: 72, trades: 2, wins: 1}); `test_missing_costs_count_as_zero` (trade without `costs` → net == realized).
- [ ] **Step 2: Run** `cd /home/ubuntu/projects/NeoTrade && pytest -q -p no:cacheprovider backend/tests/test_analytics.py` — FAIL (KeyError `net`).
- [ ] **Step 3: Implement** with `t.get("costs") or 0`.
- [ ] **Step 4: Run** — PASS, all existing analytics tests still pass.
- [ ] **Step 5: Commit** `feat(analytics): P&L net of charges per period and all time`.

### Task 2: Book period maths

**Files:** Create `frontend/src/utils/practice.js`, `frontend/src/utils/practice.test.js`

**Interfaces — Produces:** `periodSummary(trades, period, now = new Date()) -> {net, trades, wins, winRate, curve: [{t: ISO exit_at, net: cumulative}]}` for `period` in `'today' | 'month' | 'all'`, IST calendar boundaries (`Asia/Kolkata`), using closed trades' `exit_at`, `realized_pnl`, `costs`; curve sorted by exit time.

- [ ] **Step 1: Failing node tests** — fixed `now = 2026-10-06T12:00:00Z`; trades exiting 2026-10-06T05:00Z (net 10), 2026-10-02T05:00Z (net −4), 2026-09-30T05:00Z (net 7, costs missing): `today` → net 10, trades 1; `month` → net 6, trades 2, winRate 0.5; `all` → net 13, curve last point 13, curve length 3; empty list → `{net: 0, trades: 0, wins: 0, winRate: null, curve: []}`.
- [ ] **Step 2: Run** `cd frontend && node --test src/utils/practice.test.js` — FAIL.
- [ ] **Step 3: Implement**; IST day start via `new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))`-free arithmetic: shift by +5:30 to get the IST date string, compare `YYYY-MM-DD` / `YYYY-MM` prefixes of shifted `exit_at`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(practice): period summary for the book`.

### Task 3: Engine page

**Files:** Modify `frontend/src/pages/PaperOverview.jsx`, `frontend/src/components/paper/EngineNow.jsx`, `frontend/src/components/paper/PaperShell.jsx` (marker only); Create `frontend/src/components/paper/TodayNet.jsx`, `frontend/src/components/paper/TradedToday.jsx`

**Interfaces — Consumes:** Task 1 `pnl.today.{net,realized,costs,unrealized,trades,wins,losses}`; `endpoints.trading.fills('paper')` (existing); the one-line strategy count comes from `GET /strategies/library` for both modes (count cards whose `statusOf` is `live-ready`).

- [ ] **Step 1:** PaperOverview renders, in order: `PaperShell` marker (no intro paragraph), `EngineNow`, `TodayNet`, `TradedToday`, a one-line link "N strategies · M ready for real money ›" to `/practice/strategies`. Delete the decision banner, `PnlStatement`, `StrategyReadiness`, the record `<details>` and the learning `<details>` and their state/fetches (`trades`, `pending`, `recordOpen`, `book`); `?book=` on `/practice` navigates to `/practice/strategies?book=…` (replace).
- [ ] **Step 2:** EngineNow long-term sheet: drop the prose paragraph and its More toggle; meta line becomes "Next scan 16:00 IST · N open long-term positions" (drop the pending count — Decisions lives under AI).
- [ ] **Step 3:** `TodayNet({ pnl, loading })`: Sheet "Today" with NetLine `Net today` = `today.net + today.unrealized`, and lines Realised (after ₹costs charges), Unrealised, Trades `n (W/L)`. Live updates keep coming from the existing `useTopic('pnl')`.
- [ ] **Step 4:** `TradedToday()`: fetch paper fills, keep today's (IST), newest first, 10 then "Show all"; empty: "No fills today." Row: logo `Scrip`, side, qty, price, clock.
- [ ] **Step 5:** `npx eslint src && npm run build` — 0 errors. Commit `feat(practice): Engine shows what it is doing now`.

### Task 4: Book page

**Files:** Modify `frontend/src/pages/Portfolio.jsx`

**Interfaces — Consumes:** Task 2 `periodSummary`; existing closed trades fetch (`endpoints.trading.trades('CLOSED','paper')`), positions, fills, open orders.

- [ ] **Step 1:** Headline Sheet "Practice money": segmented Today / Month / All time (default all, kept in `?period=` via `useSearchParams`); big net (`Money`), "N closed · win rate X%" meta, the existing AreaChart fed `curve` from `periodSummary`; empty period → "No closed trades this period" and no chart. Remove the "Realised result" and "Month to date" sheets.
- [ ] **Step 2:** Open positions as compact rows: `Scrip` + "qty @ avg" on line 1, value and unrealised right-aligned; unrealised suffix "at last close" when the market is closed (read `market.open` from `GET /today`'s existing hook or `useMarketStatus` if present — grep first, reuse). Tap a row toggles an inline action row with the existing Sell / Add buttons. Footer total unrealised.
- [ ] **Step 3:** Executions: first 10, "Show more" reveals the rest returned; meta "latest N of M".
- [ ] **Step 4:** `npx eslint src && npm run build` — 0 errors. Commit `feat(practice): Book is one money view with a period switch`.

### Task 5: Strategies tab

**Files:** Create `frontend/src/pages/Strategies.jsx`; Delete `frontend/src/pages/Library.jsx`, `frontend/src/components/paper/StrategyReadiness.jsx` (if no other importer), `frontend/src/components/dashboard/PnlStatement.jsx` (if no other importer); Modify `frontend/src/components/layout/sections.js` (`PRACTICE_TABS`), `frontend/src/App.jsx` (route + redirect keeping `location.search`)

**Interfaces — Consumes:** `GET /strategies/library?mode=` (cards with `statusOf`, `recordLine`, `strategyName` from `utils/library`), `endpoints.settings.promotion` + `utils/promotion.readiness`, `Scorecard` (`mode` prop), `LearningSheet`.

- [ ] **Step 1:** Summary line: counts by `statusOf` across the loaded mode — "M ready for real money · K paper · J not backtested · P paused".
- [ ] **Step 2:** Intraday / Long-term tabs (existing). Rows: name, status `Badge`, `recordLine(card)`, and the gate line from `readiness(promotion[name], live)`; promotion failure → "Couldn't load what it still needs". Tap toggles best-when / avoid / style detail. Header action "Live switches in Setup ›" → `/practice/setup`.
- [ ] **Step 3:** "Track record" section: the Intraday / Long term / All selector driven by `?book=` and `Scorecard mode`, plus paper trades `TradeLedger` collapsed under "Every paper trade". Then `<details>` "What the engine learned" lazily rendering `LearningSheet`.
- [ ] **Step 4:** Tabs and routes: `PRACTICE_TABS` labels Engine, Book, Strategies, Setup; `/practice/strategies` → `Strategies`; `/practice/library` → redirect with search preserved; grep every `/practice/library` link and repoint.
- [ ] **Step 5:** `npx eslint src && npm run build` — 0 errors. Commit `feat(practice): Strategies answers which strategy is good enough`.

### Task 6: Docs, ship, verify

**Files:** Modify `PRODUCT.md` (Practice → Engine, Book rows; Library row → Strategies), `frontend/src/handbook/trading-and-money.md` (Practice section)

- [ ] **Step 1:** Update the docs to the new tab contents.
- [ ] **Step 2:** Full backend suite `pytest -q -p no:cacheprovider backend/tests` and frontend `node --test src/utils/*.test.js && npm run build` — all pass.
- [ ] **Step 3:** Push (HEAD `[skip ci]`); deploy clone `git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend`.
- [ ] **Step 4:** After Vercel serves the new bundle: screenshots 390 px and 1440 px of `/practice`, `/practice/book`, `/practice/strategies`; phone `scrollWidth == 390` on each; `/practice/library?book=intraday` lands on Strategies with that book. One fix batch, one confirm round.
