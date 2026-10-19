# Daily workstation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five-tab (six for admin) workstation layout plus a Today page that reorders itself by market phase.

**Architecture:** Wave A is frontend-only: new nav constants, a pure redirect table, route moves, one merged stock page, guardrails moved into Journal. Wave B adds `phase` and phase-specific fields to `GET /today` (from `backend/core/market_calendar.py`) and a pure phase-to-sections map that Today renders. A and B touch disjoint code and run as two parallel worktrees.

**Tech Stack:** React 19 + react-router + Vite (tests: `node:test`, run with `node --test <files>`); FastAPI + Motor (tests: pytest, gate in the prod image).

**Spec:** `docs/superpowers/specs/2026-10-19-daily-workstation-design.md`

## Global Constraints

- Frontend tests are `node:test` files `*.test.js` next to the module; run `cd frontend && node --test $(find src -name '*.test.js')`. `npx vitest` finds no tests here. Always also run `npm run build`.
- Backend gate: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify python -m pytest -q backend/tests` (image is Python 3.11; no PEP 701 f-strings).
- Admin = `user?.role === 'admin'` (`useAuth()`), backend `user.role == "admin"`.
- Picks and Lab are admin only: routes wrapped in `RequireAdmin`, tabs flagged `admin: true`.
- IST phase boundaries: pre < 09:15, session 09:15 to < 15:30, post >= 15:30, closed = `not is_trading_day(date)`.
- Old paths redirect in one hop, keeping the query string (existing `Moved` component).
- A code change updates its `docs/wiki/*` page section and `verified_at` in the same commit; run `python3 docs/wiki/stale.py --orphans` before the final commit.
- Copy style: plain words, no emoji in UI text.

## Review Focus

- A bookmarked old path with a query (`/mine/journal?tab=habits`, `/research/stock/TCS`) lands on the right new page with its query: covered by the redirect-table test in Task A2.
- Non-admin opens `/picks` or `/lab/options` directly: `RequireAdmin` refuses, and no Picks/Lab tab shows; covered in A1 (visibility) and A2 (route table marks them admin).
- `/today` from an old backend (no `phase`) during a rolling deploy: Today falls back to the `session` order; covered in B2's test.
- A holiday weekday at 10:00: phase `closed`, not `session`; covered in B1.
- Symbol with `&` or `-` in the header search (`M&M`, `BAJAJ-AUTO`): URL-encoded via `stockPath`; covered in A2's `stockPath` test.

---

## Wave A: navigation and routes (worktree 1)

### Task A1: Nav constants and visibility

**Files:**
- Modify: `frontend/src/components/layout/sections.js`
- Create: `frontend/src/utils/nav.js`, `frontend/src/utils/nav.test.js`
- Modify: `frontend/src/components/layout/BottomNav.jsx`, `frontend/src/components/layout/Sidebar.jsx`

**Interfaces:**
- Produces: `visibleSections(sections, isAdmin) -> section[]` and `barColumns(count) -> string` (Tailwind class) in `utils/nav.js`. In `sections.js`: `SECTIONS` (Today `/`, Picks `/picks` admin, AI `/ai`, Portfolio `/portfolio` counter `pending`, Journal `/journal`, Lab `/lab` admin), `PORTFOLIO_TABS`, `LAB_TABS`, `AI_TABS` (Overview, Activity, Book only). `MINE_TABS` and `RESEARCH_TABS` are deleted.

- [ ] **Step 1: Write the failing test** `utils/nav.test.js`

```js
test('non-admins see four tabs, admins six', () => {
  const s = [{ path: '/' }, { path: '/picks', admin: true }, { path: '/ai' }, { path: '/portfolio' }, { path: '/journal' }, { path: '/lab', admin: true }];
  assert.deepEqual(visibleSections(s, false).map((x) => x.path), ['/', '/ai', '/portfolio', '/journal']);
  assert.equal(visibleSections(s, true).length, 6);
});
test('bar columns follow the count', () => {
  assert.equal(barColumns(4), 'grid-cols-4');
  assert.equal(barColumns(6), 'grid-cols-6');
});
```

- [ ] **Step 2:** `node --test src/utils/nav.test.js` → FAIL (module not found).
- [ ] **Step 3:** Implement `utils/nav.js`. `barColumns` returns a literal from a lookup `{4:'grid-cols-4',5:'grid-cols-5',6:'grid-cols-6'}` so Tailwind sees the class names.
- [ ] **Step 4:** Rewrite `sections.js` constants per Interfaces. `match` per section: Portfolio `['/portfolio']`, Journal `['/journal']`, Lab `['/lab']`, Picks `['/picks']`. `PORTFOLIO_TABS`: Overview `/portfolio` (end, counter), Holdings `/portfolio/holdings`, Tax `/portfolio/tax`, News `/portfolio/news`, Watchlist `/portfolio/watchlist`, Import `/portfolio/import`. `LAB_TABS`: Strategies `/lab` (end), Autopilot limits `/lab/limits`, Options `/lab/options`, Handbook `/lab/handbook`, Backlog `/lab/backlog`. Icons from lucide-react: Sun, Sparkles (Picks), Bot, Wallet, NotebookPen (Journal), FlaskConical (Lab).
- [ ] **Step 5:** BottomNav and Sidebar call `visibleSections(SECTIONS, user?.role === 'admin')`; BottomNav's `<ul>` uses `barColumns(visible.length)` instead of `grid-cols-5`.
- [ ] **Step 6:** `node --test src/utils/nav.test.js` → PASS. (Build will fail until A2 swaps the page imports; do not commit separately, commit with A2.)

### Task A2: Routes, redirects, page tab swaps, header

**Files:**
- Create: `frontend/src/utils/routes.js`, `frontend/src/utils/routes.test.js`
- Modify: `frontend/src/App.jsx`, `frontend/src/utils/stocks.js`, `frontend/src/utils/mine.js`, `frontend/src/components/layout/Masthead.jsx`, `frontend/src/components/ChatWidget.jsx:168-169`, every page importing `MINE_TABS`/`RESEARCH_TABS`/`AI_TABS` (MineOverview, MineHoldings, MineTax, MineStock, Journal, News, Watchlist, Picks, OptionChain, Dashboard, AiLimits, AiOverview, AiActivity, `components/paper/PaperShell.jsx`, Strategies), `MineHoldings.jsx:115`, `MineOverview.jsx:47`

**Interfaces:**
- Consumes: `PORTFOLIO_TABS`, `LAB_TABS`, `AI_TABS` from A1.
- Produces: `ROUTES: string[]` (every real route path), `ADMIN_ROUTES: string[]`, `MOVED: [from, to][]` in `utils/routes.js`; `stockPath(symbol)` now returns `/stock/<encoded bare symbol>`.

- [ ] **Step 1: Write the failing test** `utils/routes.test.js`

```js
test('every redirect lands on a real route in one hop', () => {
  const real = new Set(ROUTES);
  for (const [from, to] of MOVED) {
    assert.ok(real.has(to.split('?')[0]), `${from} -> ${to}`);
    assert.ok(!MOVED.some(([f]) => f === to.split('?')[0]), `${to} is itself moved`);
  }
});
test('old paths map where the spec says', () => {
  const m = Object.fromEntries(MOVED);
  assert.equal(m['/mine'], '/portfolio');
  assert.equal(m['/mine/journal'], '/journal');
  assert.equal(m['/research/news'], '/portfolio/news');
  assert.equal(m['/ai/settings'], '/lab/limits');
  assert.equal(m['/system'], '/lab/handbook');
  assert.equal(m['/research'], '/');
  assert.equal(m['/import'], '/portfolio/import');
});
test('picks and lab are admin routes', () => {
  for (const p of ['/picks', '/lab', '/lab/limits', '/lab/options', '/lab/handbook', '/lab/backlog']) assert.ok(ADMIN_ROUTES.includes(p));
});
test('stockPath encodes', () => {
  assert.equal(stockPath('M&M'), '/stock/M%26M');
  assert.equal(stockPath('NSE:BAJAJ-AUTO'), '/stock/BAJAJ-AUTO');
});
```

- [ ] **Step 2:** `node --test src/utils/routes.test.js` → FAIL.
- [ ] **Step 3:** Write `utils/routes.js`. `MOVED` = the spec's route table old paths plus every pair in today's `App.jsx` `Moved` list, each retargeted to its final new path (e.g. `/ai/autopilot` → `/lab/limits`, `/practice/strategies` → `/lab`, `/portfolio` is no longer a `from`, `/watchlist` → `/portfolio/watchlist`, `/options` → `/lab/options`, `/scanner` → `/`, `/mine/habits` → `/journal?tab=habits`, `/mine/trades` → `/journal`, `/mine/ideas` → `/portfolio`, `/decisions` → `/portfolio`, `/ai/strategies` → `/lab`, `/system/future` → `/lab/backlog`, `/research/picks` → `/picks`, `/research/options` → `/lab/options`, `/research/watchlist` → `/portfolio/watchlist`). Dynamic stock paths are not in `MOVED`; App.jsx handles them with a small `StockMoved` that reads `:symbol`.
- [ ] **Step 4:** `stockPath` in `utils/stocks.js` → `/stock/...`; `utils/mine.js:11`, `MineHoldings.jsx:115`, `MineOverview.jsx:47` use `stockPath`. ChatWidget matches `/stock/:symbol`.
- [ ] **Step 5:** App.jsx: render real routes per the spec table (`/journal` keeps `JournalMoved`'s query mapping inline: `?tab=patterns|learning` → `habits`), `MOVED.map(...)` with `Moved`, `/mine/stock/:symbol` and `/research/stock/:symbol` → `StockMoved`. Delete the old inline list.
- [ ] **Step 6:** Swap page imports: Mine pages + News + Watchlist + Import use `PORTFOLIO_TABS` label "Portfolio"; Picks drops section tabs (single page); OptionChain, Strategies, AiLimits, Handbook, Backlog use `LAB_TABS` label "Lab"; Dashboard drops tabs. Journal (`lockedAccount`) drops section tabs (Journal is its own top-level tab).
- [ ] **Step 7:** Masthead: add the existing `SmartSearch` (from `components/dashboard/SmartSearch`) in compact form that navigates to `stockPath(symbol)` on pick (hidden below `sm`, an icon button opening it on phone), and a `Settings` icon `Link` to `/settings` using `ICON_BUTTON`.
- [ ] **Step 8:** `node --test $(find src -name '*.test.js')` → all PASS; `npm run build` → success.
- [ ] **Step 9: Commit** A1 + A2: `feat(nav): workstation tabs (Today, Picks, AI, Portfolio, Journal, Lab) and one-hop redirects`.

### Task A3: One stock page

**Files:**
- Modify: `frontend/src/pages/MineStock.jsx`, `frontend/src/pages/Dashboard.jsx`, `frontend/src/App.jsx`

**Interfaces:**
- Consumes: `stockPath` from A2.
- Produces: route `/stock/:symbol` → `MineStock`; Dashboard's analysis body extracted as `export const StockAnalysis = ({ symbol }) => ...` in `Dashboard.jsx`.

- [ ] **Step 1:** Extract Dashboard's per-symbol analysis (the `quick_analyze` stream, verdict, chart sections it renders when `symbol` is set) into `StockAnalysis({ symbol })`; Dashboard without a symbol is no longer routed (its search moved to the header in A2), so Dashboard keeps only `StockAnalysis` exported. Remove the dead search-landing UI.
- [ ] **Step 2:** MineStock renders its position/lots/thesis blocks only when held (it already loads the holding; when absent, skip those blocks instead of an empty state), then `<StockAnalysis symbol={symbol} />`. Remove the "Research" link at `MineStock.jsx:126`.
- [ ] **Step 3:** `/stock/:symbol` route → `MineStock`. `npm run build` → success; open `/stock/TCS` (not held) and a held symbol in `npm run dev` with the backend URL, check both render.
- [ ] **Step 4: Commit** `feat(stock): one stock page at /stock/:symbol`.

### Task A4: Guardrails tab in Journal

**Files:**
- Create: `frontend/src/components/journal/GuardrailsSheet.jsx` (moved from `Settings.jsx:900-1264`, with `GUARD_FIELDS`)
- Modify: `frontend/src/pages/Settings.jsx`, `frontend/src/pages/Journal.jsx`

**Interfaces:**
- Produces: Journal tabs `trades | habits | guardrails` via existing `useTab`; `/journal?tab=guardrails`.

- [ ] **Step 1:** Move `GuardrailsSheet` + `GUARD_FIELDS` verbatim to the new file (default export); Settings imports nothing from it. Settings' `safety` tab keeps `PortfolioSheet`; `LEGACY_TABS.guardrails` now redirects to `/journal?tab=guardrails` (navigate, replace).
- [ ] **Step 2:** Journal: `useTab(['trades','habits','guardrails'])` (keep the `view` default ordering), third segment "Guardrails" renders `<GuardrailsSheet />` in place of the trades/habits body.
- [ ] **Step 3:** `npm run build` → success; tests PASS.
- [ ] **Step 4: Commit** `feat(journal): guardrails live under Journal`.

### Task A5: App paths in backend texts and docs

**Files:**
- Modify: any `backend/**/*.py` string containing `/mine`, `/research`, `/ai/settings`, `/ai/strategies`, `/system`, `/import` used as an app link (find with `grep -rnE "\"/(mine|research|import|system)|/ai/(settings|strategies)" backend --include=*.py | grep -v routers/ | grep -v "prefix="`); `backend/routers/today.py` `needs_you` `to` values; `frontend/src/handbook/*.md`; `PRODUCT.md` Surfaces; `docs/wiki/` frontend page map; `docs/ROADMAP.md` Phase 21 step 2 status line.
- Test: `backend/tests/test_today.py` (update expected `to` paths)

- [ ] **Step 1:** Replace app-link strings with new paths (API route paths under `/api/v1/...` are NOT app links; leave them). Update the matching assertions in tests.
- [ ] **Step 2:** In-image pytest → PASS.
- [ ] **Step 3:** Docs updated; `python3 docs/wiki/stale.py --orphans` → `wiki current`.
- [ ] **Step 4: Commit** `docs+links: point texts and docs at the workstation paths`.

---

## Wave B: phase-aware Today (worktree 2)

### Task B1: `/today` phase fields

**Files:**
- Modify: `backend/routers/today.py`, `backend/portfolio/digest.py`
- Test: `backend/tests/test_today.py`

**Interfaces:**
- Produces: `market_phase(now: datetime) -> str` and `next_open(now: datetime) -> datetime` in `backend/core/market_calendar.py`; `digest.premarket_for(db, user_id, now) -> str` and `digest.postclose_for(db, user_id, now) -> str` (the bodies `send_premarket` / `send_postclose` build today, now shared by both); `/today` keys `phase`, `next_open`, `premarket` (str|None), `postclose` (str|None), `unjournaled` (int|None), `picks_top` (list|None).

- [ ] **Step 1: Write failing tests** in `backend/tests/test_market_calendar.py`:

```python
@pytest.mark.parametrize("at,phase", [
    (datetime(2026, 10, 19, 9, 14, tzinfo=IST), "pre"),
    (datetime(2026, 10, 19, 9, 15, tzinfo=IST), "session"),
    (datetime(2026, 10, 19, 15, 29, tzinfo=IST), "session"),
    (datetime(2026, 10, 19, 15, 30, tzinfo=IST), "post"),
    (datetime(2026, 10, 24, 11, 0, tzinfo=IST), "closed"),   # Saturday
    (datetime(2026, 10, 20, 10, 0, tzinfo=IST), "closed"),   # NSE holiday
])
def test_market_phase(at, phase):
    assert market_calendar.market_phase(at) == phase

def test_next_open_skips_the_holiday():
    assert market_calendar.next_open(datetime(2026, 10, 19, 16, 0, tzinfo=IST)) == datetime(2026, 10, 21, 9, 15, tzinfo=IST)
```

and in `test_today.py` (using its existing fixtures/fakes): `/today` at a pre-market time returns `phase == "pre"` and a `premarket` string starting `"☀️ <b>Before the open</b>"`; at a post time `postclose` is a str and `premarket` is None; `picks_top` is None for a non-admin; `unjournaled` counts today's closed `mine` round trips whose note is empty (one noted, two not → 2).

- [ ] **Step 2:** Run them in the image → FAIL.
- [ ] **Step 3:** Implement `market_phase` / `next_open` (IST, `is_trading_day`, `next_trading_day`). Move the per-user bodies of `send_premarket` / `send_postclose` into `premarket_for` / `postclose_for`; the senders call them (no behaviour change, existing digest tests must stay green).
- [ ] **Step 4:** In `today()`: `phase = market_phase(now)`; `premarket` only when `pre`, `postclose` when `post` or `closed`; `picks_top` only when admin and `pre` = first 3 of the latest `PICKS` date sorted as `routers/picks.py::picks_today` sorts (extract that sort key to `forecast/picks.py::rank_key(p)` and use it in both); `unjournaled` = closed `mine` trips with `closed_at` on today's IST date and empty note (use `journal.accounts.filter_trades` + `brokers_of(roles, "mine")`, `build_round_trips`, `JournalStore.notes_for`). Every new field goes through `part(...)`.
- [ ] **Step 5:** In-image pytest → PASS (full suite).
- [ ] **Step 6:** Update `docs/wiki` page covering `routers/today.py` and `core/market_calendar.py` (Endpoints row for `/today`); commit `feat(today): market phase and phase texts on /today`.

### Task B2: Today renders by phase

**Files:**
- Create: `frontend/src/utils/todayLayout.js`, `frontend/src/utils/todayLayout.test.js`
- Modify: `frontend/src/pages/Today.jsx`

**Interfaces:**
- Consumes: `/today` keys from B1.
- Produces: `sectionsFor(phase) -> string[]` of ids from `'beforeOpen','picksTop','doToday','account','aiActivity','markets','afterClose','journalPrompt','scoreboard','closedNote'`; `digestLines(html) -> string[]` (strip tags, decode entities, split lines).

- [ ] **Step 1: Write failing tests**

```js
test('phase orders', () => {
  assert.deepEqual(sectionsFor('pre'), ['beforeOpen', 'picksTop', 'doToday', 'account', 'markets']);
  assert.deepEqual(sectionsFor('session'), ['doToday', 'account', 'aiActivity', 'markets']);
  assert.deepEqual(sectionsFor('post'), ['afterClose', 'journalPrompt', 'scoreboard', 'account', 'aiActivity']);
  assert.deepEqual(sectionsFor('closed'), ['closedNote', 'afterClose', 'scoreboard', 'account']);
});
test('unknown phase falls back to session', () => {
  assert.deepEqual(sectionsFor(undefined), sectionsFor('session'));
});
test('digest html becomes plain lines', () => {
  assert.deepEqual(digestLines('☀️ <b>Before the open</b>\n• M&amp;M: up'), ['Before the open', '• M&M: up']);
});
```

(`digestLines` also drops a leading emoji + space on the first line; decode `&amp; &lt; &gt; &quot; &#x27;` with a fixed map, no DOM, so it runs under node.)

- [ ] **Step 2:** `node --test src/utils/todayLayout.test.js` → FAIL.
- [ ] **Step 3:** Implement `todayLayout.js`.
- [ ] **Step 4:** Today.jsx: StatusStrip and SetupChecklist stay on top; map `sectionsFor(data.phase)` ids to components: `beforeOpen`/`afterClose` = `Sheet` titled "Before the open"/"After the close" listing `digestLines(text)` (skip the title line); `picksTop` = up to 3 rows (symbol linking `stockPath`, label, expected median %) linking "All picks" to `/picks`; `journalPrompt` = a row "`N` trades to journal" → `/journal`, hidden when `unjournaled` is 0/null; `closedNote` = "Market closed. Opens <formatted next_open IST>". Missing data hides a section. Desktop keeps the two-column grid: `markets` in the right column, the rest left.
- [ ] **Step 5:** tests PASS; `npm run build` → success.
- [ ] **Step 6: Commit** `feat(today): sections follow the market phase`.

---

## Merge and ship

- [ ] Merge wave A branch, then wave B (expect a trivial conflict only in docs); rerun frontend tests + build + in-image pytest on main.
- [ ] Deploy direct: HEAD subject `[skip ci]`, push, then in `/home/ubuntu/deploys/NeoTrade`: `git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend ingest jobs && docker compose up -d backend`; check `/health`. Avoid 15:30-17:00 IST. Vercel builds the frontend.
- [ ] Phone-width check of the 6-tab bar on the Vercel URL.
