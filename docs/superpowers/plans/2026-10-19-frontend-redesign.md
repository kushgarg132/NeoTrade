# Frontend redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild NeoTrade's frontend around a hub Home and five tabbed areas (Money, Ideas, AI, Market, Stock) in a clean modern light/dark style, plus daily brief, goal tracker and weekly report.

**Architecture:** In-place rebuild of the React 19 + Vite + Tailwind 4 app. Task 1 lays the design tokens, `components/ui/` primitives, the new shell and every new route (pointing at stub pages) plus all redirects, so the area tasks in wave 2 each own disjoint files. Existing data hooks/fetches and components are reused inside the new layouts; old page files are deleted by the task that replaces them.

**Tech Stack:** React 19, react-router, Tailwind 4 (CSS variables), lucide-react, recharts; FastAPI backend for goal + weekly report.

**Spec:** `docs/superpowers/specs/2026-10-19-frontend-redesign-design.md` (mockups in `.superpowers/brainstorm/554992-1792414279/content/`).

## Global Constraints

- Phone first: 390 px design width, 44 px touch targets, body 15 px, nothing functional below 12 px, text contrast ≥ 4.5:1 on its surface (light and dark).
- Tokens only (no raw hex in components): `--bg --surface --surface-2 --border --text --text-muted --accent --gain --loss --warn`; radius 12/16; 4-px spacing; numbers `font-variant-numeric: tabular-nums`.
- Tabs are URL-backed: `?tab=<id>`; default tab when absent.
- Every data section: `Skeleton` while loading, one-line error + Retry, `Empty` with its fill action. One failing section never blanks a page.
- Keep: privacy mask (`private` class / `usePrivacy`), live socket hooks, second-tap live-order flow (`utils/liveConfirm.js`, OrderTicket), admin gating (`RequireAdmin`, `user.role === 'admin'`), ChatWidget.
- Frontend tests are `node:test` (`node --test $(find src -name '*.test.js')`) + `npm run build`. Backend tests in the prod image: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify sh -c "python -m pytest -q backend/tests; lint-imports --config backend/.importlinter"`.
- Wiki `frontend.md` (+ others touched) section and `verified_at` in the same commit; `python3 docs/wiki/stale.py --orphans` → "wiki current". Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Old bookmarks: every pre-redesign route lands on its new home in one hop with its query (routes test).
- Privacy mask still hides every ₹ amount on every new screen (eye toggle).
- Live Buy/Sell still requires the server second tap (existing flow, not a new button that skips it).
- Non-admin never sees Lab, Picks rows or admin badges.
- Dark mode: no unreadable text (contrast) on any new screen.

---

## Wave 1

### Task 1: Design system, shell, routes, redirects

**Files:**
- Modify: `frontend/src/index.css` (new tokens light/dark; remove paper/ink/stamp tokens only after nothing references them — keep aliases mapping old names to new tokens so untouched components still render), `frontend/src/App.jsx`, `frontend/src/components/Layout.jsx`, `frontend/src/components/layout/*` (new `Header.jsx`, `BottomTabs.jsx`, `SideRail.jsx`; old Masthead/BottomNav/Sidebar/SectionTabs removed or replaced), `frontend/src/utils/routes.js` (+ test)
- Create: `frontend/src/components/ui/{Tile,Card,Stat,Tabs,ListRow,Badge,Button,PageHeader,Empty,Skeleton,ErrorLine}.jsx`, `frontend/src/components/ui/format.js` (+ `format.test.js`), stub pages `frontend/src/pages/{Home,Money,Ideas,IdeaDetail,IdeasHistory,Ai,Market,Stock,SettingsHome,WeeklyReport}.jsx` (each renders `PageHeader` + "Coming in this redesign" `Empty`), stub `frontend/src/components/home/{GoalTile,BriefCard,WeeklyLink}.jsx` returning null.

**Interfaces (produced):**
- `Tile({title, value, sub, tone, to, icon})`, `Card({title, action, children})`, `Stat({label, value, delta, tone})`, `Tabs({tabs:[{id,label,badge?}], value, onChange})` + `useTabParam(ids, default) -> [tab, setTab]`, `ListRow({title, sub, right, rightTone, to, onClick, chevron=true})`, `Badge({kind:'proven'|'unproven'|'paper'|'live'|'alert'|'neutral', children})`, `Button({variant:'primary'|'secondary'|'danger', ...})`, `PageHeader({title, back, right})`, `Empty({title, body, action})`, `Skeleton({rows})`, `ErrorLine({message, onRetry})`.
- `format.js`: `inr(n, {sign})`, `pct(x, {sign, dp})`, `tone(x) -> 'gain'|'loss'|'neutral'`, `compactInr(n)` (₹4.09L, ₹1.2Cr).
- Routes: `/` Home, `/money`, `/ideas`, `/ideas/history`, `/ideas/:id`, `/ai`, `/market`, `/stock/:symbol`, `/settings` (+ `/settings/lab/*` admin: `strategies, options, runs, forward, handbook, backlog` rendering the existing pages), `/reports/weekly`, `/login`, `/profile` kept.
- Redirects (`MOVED` in `utils/routes.js`, one hop, query kept): `/portfolio`→`/money`; `/portfolio/holdings`→`/money?tab=holdings`; `/portfolio/tax`→`/money?tab=tax`; `/portfolio/import`→`/money?tab=holdings`; `/portfolio/news`→`/market?tab=news`; `/portfolio/watchlist`→`/market?tab=watchlist`; `/journal`→`/money?tab=journal` (old `?tab=habits|guardrails` becomes `jtab`); `/picks`→`/ideas`; `/ai/book`→`/ai?tab=positions`; `/ai/activity`→`/ai?tab=activity`; `/lab`→`/settings/lab/strategies`; `/lab/limits`→`/settings?tab=limits`; `/lab/options|runs|forward|handbook|backlog`→`/settings/lab/<same>`; plus every older entry already in `MOVED` retargeted to final paths.

- [ ] **Step 1: Failing tests:** `format.test.js` (`inr(409205)` = "₹4,09,205"; `compactInr(409205)` = "₹4.09L"; `pct(0.0165,{sign:true})` = "+1.65%"; `tone(-1)` = "loss"); `routes.test.js` updated (one hop, query kept, admin routes include `/settings/lab/*`, each spec redirect above).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement tokens, primitives, shell (Header: search via existing `SmartSearch` → `/stock/:symbol`, market dot, privacy eye, theme toggle, profile → `/settings`; BottomTabs 5 tabs with badges from existing counters; desktop SideRail), routes, stubs. **Step 4:** tests + build green; screenshot `/` at 390 px light/dark (Playwright pattern: fake `/api/v1/**`, `localStorage neotrade_token`).
- [ ] **Step 5:** Wiki `frontend.md` (shell, tokens, route map). Commit `feat(fe): design system, shell and route map for the redesign`.

---

## Wave 2 (parallel: Tasks 2-7; each owns only its listed files)

### Task 2: Home
**Files:** `pages/Home.jsx`, `components/home/BriefCard.jsx`, `components/home/WeeklyLink.jsx`, `components/home/*` new helpers; delete `pages/Today.jsx` after porting.
- Today line (phase + "N need you" → `/ideas` + setup checklist until done), BriefCard (`/today` `premarket` before 09:15 / `postclose` after 15:30; 3 lines + "Read all"; uses existing `digestLines`), 4 `Tile`s (Money: value/today/XIRR; Ideas: count + "N proven · M exit"; AI: today % + month vs you; Market: NIFTY % + regime), `<GoalTile/>` (stub from T1, filled by T8), `<WeeklyLink/>` (Sun/Mon only → `/reports/weekly`).
- Tests: `utils/home.js` `tileHeadlines(today, overview) -> {money, ideas, ai, market}` with node:test on missing/partial data.
- Commit `feat(fe): Home hub`.

### Task 3: Money
**Files:** `pages/Money.jsx`, `components/money/*`; delete `pages/MineOverview.jsx`, `MineHoldings.jsx`, `MineTax.jsx`, `Import.jsx` (fold import into Holdings footer), and move Journal into `components/money/JournalTab.jsx` (delete `pages/Journal.jsx`), GuardrailsSheet stays as used by JournalTab.
- Header (value, today ₹/%, XIRR vs NIFTY), tabs Overview (value vs NIFTY chart 1M/6M/1Y/All from `/mine/history`, invested, total P&L, top 3 movers + why) · Holdings (sortable list: today %, value, weight, total P&L, why, verdict badge → stock page; import link) · Tax (`/mine/tax`) · Journal (trades/habits/guardrails via `jtab`).
- Tests: `utils/money.js` `sortHoldings`, `topMovers`, `whyLine(holding)` (fallback "Moved with the market").
- Commit `feat(fe): Money area`.

### Task 4: Ideas
**Files:** `pages/Ideas.jsx`, `pages/IdeaDetail.jsx`, `pages/IdeasHistory.jsx`, `components/ideas/*`; delete `pages/Picks.jsx` after porting.
- List: Exit alerts (`/mine/actions`: Sell/Later/Dismiss via existing actions) then New ideas (`/suggestions` for_mine + `/picks` for admin); rows with action, symbol, setup, horizon, median %, `Badge` proven/unproven (from `/forward/scorecard` via existing `useForward`/`badgeFor`).
- Detail `/ideas/:id` (`id` = `s-<suggestionId>` or `p-<pickId>`): why (rule codes in words), Entry/Stop/Target, size (qty, ₹, risk ₹), range bar p10/median/p90, chance up, beat NIFTY, track record (past n, OOS excess, forward n/100), Buy (existing second-tap approve-live) / Skip (reject).
- History: Picks history + scored forward records, newest first.
- Tests: `utils/ideas.js` `ideaFromSuggestion`, `ideaFromPick` → one view model; `rangeBar(p10, median, p90)` positions.
- Commit `feat(fe): Ideas list, detail and history`.

### Task 5: Stock page
**Files:** `pages/Stock.jsx`, `components/stock/*`; delete `pages/MineStock.jsx`, `pages/Dashboard.jsx` after moving `StockAnalysis` into `components/stock/AnalysisTab.jsx`.
- Header: price, today move, verdict badge, your position (qty, avg, P&L, weight) if held; tabs Chart (1D/1M/1Y/5Y, your buys/sells marked; reuse existing chart component) · News · Analysis · Events; sticky bottom Buy/Sell opening the existing order ticket (second tap kept).
- Tests: `utils/stock.js` `positionSummary`, `tradeMarkers`.
- Commit `feat(fe): stock page with tabs`.

### Task 6: AI
**Files:** `pages/Ai.jsx`, `components/ai/*`; delete `pages/AiOverview.jsx`, `AiActivity.jsx`, `Portfolio.jsx` (AI book), `components/paper/PaperShell.jsx` if unused.
- Header: value, today %, paper/live `Badge`, Stop AI (`Button` danger → existing kill-switch / StopAutopilot with confirm); tabs Scoreboard (month AI vs you vs NIFTY, win rate, trades, charges, max DD, strategies + proven status) · Positions (AI book) · Activity (log with reasons).
- Tests: `utils/ai.js` `scoreboard(summary)` formatting.
- Commit `feat(fe): AI area`.

### Task 7: Market and Settings
**Files:** `pages/Market.jsx`, `components/market/*`, `pages/SettingsHome.jsx`, `components/settings/*`; delete `pages/News.jsx`, `Watchlist.jsx` after porting; `pages/Settings.jsx` is split into `components/settings/{Accounts,Alerts,Limits,Profile,Theme,Lab}.jsx` sections (Goal section stub for T8).
- Market tabs Pulse (indices, sectors, breadth, regime, events from `/today` `backdrop` + `/market/indices`) · Watchlist · News (holdings first).
- Settings tabs Accounts · Alerts · Limits (guardrails + AiLimits) · Profile · Theme · Goal (stub) · Lab (admin: links to `/settings/lab/*`).
- Tests: `utils/market.js` `sectorRows`; settings has no new logic beyond moved code.
- Commit `feat(fe): Market and Settings areas`.

---

## Wave 3 (parallel: Tasks 8, 9)

### Task 8: Goal tracker
**Files:** backend `backend/prefs.py` (field `goal`), `backend/routers/settings.py` (validation), tests `backend/tests/test_goal_prefs.py`; frontend `components/home/GoalTile.jsx`, `components/settings/Goal.jsx`, `utils/goal.js` (+ test).
- Prefs `goal = {kind: "value"|"beat_nifty", target: float, by: "YYYY-MM-DD", start: "YYYY-MM-DD", start_value: float|null}`; 422 when target ≤ 0 or `by` not in the future; `start`/`start_value` set server-side on save.
- `utils/goal.js`: `progress(goal, overview, history) -> {pct, pace: 'ahead'|'on'|'behind', neededMonthly, actualMonthly}`; value: (value − start_value)/(target − start_value); beat_nifty: (your return − NIFTY return since start)/target. Pace compares needed monthly growth to trailing 3-month actual.
- Tests: node:test for progress/pace edges; pytest validation.
- Commit `feat: goal tracker`.

### Task 9: Weekly report
**Files:** backend `backend/reports/weekly.py`, `backend/routers/reports.py` (mount, user-scoped), scheduler/jobs hook for Sunday 18:00 IST Telegram, tests `backend/tests/test_weekly_report.py`; frontend `pages/WeeklyReport.jsx`, `components/home/WeeklyLink.jsx` only if T2 left it a stub.
- `GET /api/v1/reports/weekly?week=YYYY-Www` (default last completed ISO week): `{week, you:{ret, nifty, excess}, ai:{ret}, best:[3], worst:[3], ideas:{taken:{n, mean_excess}, skipped:{n, mean_excess}}, journal:{trades, net, charges}}` from existing sources (`mine/history`, AI ledger, forward records joined to suggestion status, journal round trips). `text(report) -> str` (Telegram HTML, same builder the page mirrors).
- Sunday 18:00 IST: once per user per ISO week (`report:weekly:<uid>:<week>` Redis NX, 8 days).
- Tests: fixtures for each number; send-once guard; week parsing.
- Commit `feat: weekly report`.

---

## Ship

- [ ] Work on local branch `fe-redesign` (Vercel deploys every push to `main`, so main must not see stub pages). The controller creates each task's worktree by hand from `fe-redesign` (`git worktree add .claude/worktrees/fe-tN -b fe-tN fe-redesign`) and dispatches implementers into those paths; no `isolation: worktree` (it branches from origin/main).
- [ ] Merge each wave in task order; gate (backend image suite + lint, node tests, build, stale.py); Playwright screenshots 390/1280 light/dark of every area.
- [ ] Final whole-branch review; one fix wave.
- [ ] Merge `fe-redesign` into `main` only when every area works; push (`[skip ci]` on HEAD) → Vercel builds the frontend; deploy backend (T8/T9) direct via the deploy clone, backend first.
