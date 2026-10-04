# Practice Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/ai/practice` says what it is, what the engine is doing now, and whether each strategy is working, in that order.

**Architecture:** Frontend only. The run controls move from `Trading.jsx` into an `EngineNow` component on the Overview; the fills table moves to the holdings page, renamed Book; `Trading.jsx` is deleted. A shared `promotionGaps` helper feeds a new per-strategy readiness sheet.

**Tech Stack:** React 19, Vite, react-router, Tailwind tokens in `frontend/src/index.css`, `node --test` for the one pure helper.

**Spec:** `docs/superpowers/specs/2026-10-04-practice-page-design.md`

## Global Constraints

- No backend change; no new npm dependency.
- `PaperShell`'s dashed stamp stays on every Practice page.
- Practice stays at `/ai/practice` under the AI tabs.
- Intro copy, verbatim: "The strategy engine trades practice money here. Its rules decide; AI adds at most 30% to a trade's score. The AI autopilot is separate →" followed by a link "AI Overview" to `/ai`.
- Every redirect lands in one hop (no `Moved` → `Moved` chain).
- Each sheet loads and fails on its own; one failed fetch never blanks the page.
- Session deploy mode is **Direct**: commit subjects end `[skip ci]`; Vercel builds the frontend on push. No backend redeploy needed.

## Review Focus

1. A promotion row whose last backtest has `profit_factor: null` (zero trades) must not throw — `promotionGaps` currently calls `.toFixed` on it. Test in Task 1.
2. A strategy name with no promotion row (new strategy, no record yet) shows "No paper record yet", not a crash or blank. Covered in Task 2 Step 3.
3. A deep link `/ai/practice?book=intraday` opens the track record expanded with Intraday selected, since the filter now sits inside a collapsed `<details>`. Task 2 Step 4.
4. Start/Stop and live progress keep working after the move: `EngineNow` keeps the `runs`, `trades` and `suggestions` topic subscriptions it had in `Trading.jsx`. Task 2 manual check.
5. Four sub-tabs at 375px width fit on their short names without horizontal scroll. Task 3 manual check.

---

### Task 1: Shared `promotionGaps`

**Files:**
- Create: `frontend/src/utils/promotion.js`
- Create: `frontend/src/utils/promotion.test.js`
- Modify: `frontend/src/components/paper/EngineSettings.jsx:20-42` (remove `GAP` and `promotionGaps`, import instead)

**Interfaces:**
- Produces: `export function promotionGaps(row) -> string` — comma-joined gaps, `''` when none. `row` is one element of `GET /settings/strategies/promotion`: `{ name, backtest_passed, backtest: {trades, days, profit_factor, max_drawdown} | null, paper: { passed, checks: [{rule, ok, need, have}] }, eligible }`.

- [ ] **Step 1: Write the failing test** with `node:test` + `node:assert/strict`:
  - `passing row has no gaps`: `backtest_passed: true`, all checks `ok: true` → `''`.
  - `names a missing backtest and a weak profit factor`: `backtest: null`, `backtest_passed: false`, one check `{rule:'profit_factor', ok:false, need:1.3, have:1.1}` → `'a passing backtest (none run yet), profit factor 1.3 (now 1.1)'`.
  - `null backtest profit factor does not throw`: `backtest: {trades:0, days:365, profit_factor:null, max_drawdown:0}`, `backtest_passed:false`, no checks → `'a passing backtest (last: 0 trades over 365 days, profit factor –)'`.
- [ ] **Step 2:** `node --test frontend/src/utils/promotion.test.js` → FAIL (module not found).
- [ ] **Step 3:** Move `GAP` and `promotionGaps` verbatim from `EngineSettings.jsx` into `promotion.js`, exported; print `–` when `profit_factor` is null. `EngineSettings.jsx` imports it.
- [ ] **Step 4:** Test → PASS. `npm --prefix frontend run build` → built.
- [ ] **Step 5: Commit** `refactor(practice): share promotionGaps; survive a zero-trade backtest [skip ci]`.

### Task 2: Overview answers what / now / working

**Files:**
- Create: `frontend/src/components/paper/EngineNow.jsx`
- Create: `frontend/src/components/paper/StrategyReadiness.jsx`
- Modify: `frontend/src/pages/PaperOverview.jsx` (rewrite render order)
- Modify: `frontend/src/pages/Trading.jsx` (render only the Positions and Executions sheets; Task 3 deletes it)

**Interfaces:**
- Consumes: `promotionGaps(row)` from Task 1.
- Produces: `EngineNow` (no props) — the live-armed band, *Intraday engine* sheet and *Long-term engine* sheet, with all their state, loaders, `start`/`stop`/`scanNow` and `useTopic('runs'|'trades'|'suggestions')` moved unchanged from `Trading.jsx`. Drops positions/fills state (not shown here).
- Produces: `StrategyReadiness` (no props) — `<Sheet title="Is it working">`.

- [ ] **Step 1:** Create `EngineNow` by moving code from `Trading.jsx`; `Trading.jsx` keeps only its Positions and Executions sheets and their loaders.
- [ ] **Step 2:** `npm --prefix frontend run build` → built.
- [ ] **Step 3:** `StrategyReadiness` fetches `endpoints.settings.strategies`, `endpoints.settings.promotion`, `endpoints.settings.preferences`. One row per strategy name:
  - eligible → "Ready for real money" + "· live switch on/off" from `live_strategies`.
  - row present, not eligible → "Paper only. Needs {promotionGaps(row)}."
  - no row → "No paper record yet."
  - Sheet actions: link "Change in Settings ›" → `/ai/practice/settings`.
  - Promotion fetch fails → "Couldn’t load strategy readiness." in the sheet only.
- [ ] **Step 4:** Rewrite `PaperOverview` render, inside `PaperShell`, in this order: intro line (Global Constraints copy, `doc-meta normal-case`); `<EngineNow />`; `PnlStatement`; existing pending banner; `<StrategyReadiness />`; `<details>` with `<summary>` "Full track record" containing the book filter, `Scorecard`, `TradeLedger`. `<details>` is `open` when the `book` search param is set.
- [ ] **Step 5:** `npm --prefix frontend run build && npm --prefix frontend run lint` → no errors. `npm --prefix frontend run dev`, sign in: Overview shows the four blocks in order; Start then Stop a run from the Overview; progress line updates; `/ai/practice?book=intraday` opens the track record on Intraday.
- [ ] **Step 6: Commit** `feat(practice): Overview says what it is, what the engine is doing, which strategies are ready [skip ci]`.

### Task 3: Book tab, four sub-tabs, docs, ship

**Files:**
- Modify: `frontend/src/pages/Portfolio.jsx` (add Executions sheet after "Open positions")
- Modify: `frontend/src/components/paper/PaperShell.jsx:18-24,46` (tabs, `grid-cols-4`)
- Delete: `frontend/src/pages/Trading.jsx`
- Modify: `frontend/src/App.jsx` (`/ai/practice/book` → `<Portfolio />`; `/ai/practice/holdings` and `/paper/holdings` → `<Moved to="/ai/practice/book" />`; `/ai/practice/engine`, `/paper/engine`, `/trading` → `<Moved to="/ai/practice" />`; drop the `Trading` lazy import)
- Modify: `PRODUCT.md:65-69` (Practice rows)

**Interfaces:**
- Consumes: the Executions sheet markup from the old `Trading.jsx` (last 25 fills, newest first, from `endpoints.trading.fills('paper')`, refreshed on `useTopic('trades')`).

- [ ] **Step 1:** Move the Executions sheet from `Trading.jsx` into `Portfolio`, then delete `Trading.jsx`. `Portfolio` fetches fills alongside its existing `Promise.all` and renders the Executions sheet; its fills reload on the `trades` topic.
- [ ] **Step 2:** `PAPER_TABS` = Overview `/ai/practice` (end) · Decisions `/ai/practice/decisions` (short "Decide", counter) · Book `/ai/practice/book` · Settings `/ai/practice/settings` (short "Setup"); nav `grid-cols-4`. Routes as listed.
- [ ] **Step 3:** `PRODUCT.md`: replace the Practice, Holdings and Engine rows with Overview (intro, engine now, P&L, readiness, collapsed track record) and Book (equity curve, open positions, closed trades, executions); Decisions and Settings rows keep their text, Settings path unchanged.
- [ ] **Step 4:** `node --test frontend/src/utils/promotion.test.js && npm --prefix frontend run build && npm --prefix frontend run lint` → pass. Dev server at 375px: four tabs fit, no horizontal scroll; `/ai/practice/holdings`, `/paper/holdings`, `/ai/practice/engine`, `/trading` each land in one hop.
- [ ] **Step 5: Commit** `feat(practice): Book tab with executions; four sub-tabs; docs [skip ci]`, push, then `npx vercel ls neotrade` → newest Production deployment Ready; open `https://neotrade-trading.vercel.app/ai/practice` → 200.
