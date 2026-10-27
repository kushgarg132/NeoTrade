# Market + Stock Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public prices (Stock, Index, NIFTY on Market Today) on the Hero + DeltaChip without hide-amounts blur; leftover styling in market/stock/trading files fixed.

**Architecture:** Two opt-out props (`privateValue`) and a `format` prop on DeltaChip, plus a `points` formatter, unlock the existing Hero for public figures; three pages adopt it; class-only fixes elsewhere.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test`, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-market-stock-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no new npm dependency.
- Public prices never carry `private`; the user's own position figures always do.
- Text on an `--accent` fill uses `--accent-ink`.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- Hide-amounts on: Stock price, index level, NIFTY Hero readable; Stock position stats and stop line blurred.
- Live price tick every 60 s on Stock: Hero renders the new price directly (no re-count from 0).
- Non-INR stock with `dayAbs` present: chip shows percent only, arrow from `dayPct`, no ₹.
- `/market/indices` without `^NSEI` (feed gap): no Hero, no crash; BANK NIFTY / SENSEX tiles still show.
- `dayPct` exactly 0: neutral chip (no arrow) on Stock.

---

### Task 1: Primitives — points, privateValue, DeltaChip format

**Files:**
- Modify: `frontend/src/components/ui/format.js`, `frontend/src/components/ui/Hero.jsx`, `frontend/src/components/ui/DeltaChip.jsx`, `frontend/src/components/ui/signature.test.js`
- Test: `frontend/src/components/ui/format.test.js` (extend, or create if absent)

**Interfaces:**
- Produces: `points(n, { sign = false } = {}) -> string`; `Hero({ ..., privateValue = true })`; `DeltaChip({ value, pct, suffix, format = inr, privateValue = true })`.

- [ ] **Step 1: Failing tests**: `points(24812.5, { sign: true }) === '+24,812.5'`, `points(-12.345) === '-12.35'` (2 dp max, en-IN), `points(null) === '—'`, `points(0, { sign: true }) === '0'`. Source tests: Hero value class is conditional on `privateValue`; DeltaChip uses `format(value, { sign: true })`, direction from `pct` when `typeof value !== 'number'`, amount omitted when `value` not a number, `private` conditional on `privateValue`; defaults `privateValue = true`, `format = inr`.
- [ ] **Step 2: Run** `cd frontend && node --test src/components/ui/`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §1.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS (Home/Money/AI tests untouched and green).
- [ ] **Step 5: Commit** `feat(ui): Hero and DeltaChip for public figures; points format [skip ci]`.

### Task 2: Stock price on the Hero

**Files:**
- Modify: `frontend/src/pages/Stock.jsx:140-205`; Test: `frontend/src/pages/Stock.test.js` (extend or create)

**Interfaces:**
- Consumes (Task 1): `points`, `Hero privateValue`, `DeltaChip format/privateValue`.

- [ ] **Step 1: Failing source tests**: `<Hero` with `privateValue={false}` and `format={currency === 'INR' ? inr : points}`; `<DeltaChip` with `privateValue={false}` and `value={currency === 'INR' ? dayAbs : null}` and `pct={dayPct * 100}`; Watch toggle keeps `aria-pressed={watching}`; `<AsOf` inside; position block still has `data-testid="stop-line"` and `className="private"` spans; `Set one in Details` present; no `text-[28px]` price span.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §2.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(stock): price on the Hero, position in its own card [skip ci]`.

### Task 3: NIFTY hero on Market Today; Index page Hero

**Files:**
- Modify: `frontend/src/components/market/Today.jsx` (`TILES`, `IndexTile`, `Indices`, `Today`), `frontend/src/pages/IndexPage.jsx:60-84`
- Test: `frontend/src/components/market/Today.test.js` and `frontend/src/pages/IndexPage.test.js` (extend or create)

- [ ] **Step 1: Failing source tests**: Today calls `useSection(loadIndices)` once (in `Today`), `Indices` receives props; `<Hero to={indexPath('^NSEI')}` with `label="NIFTY 50"`, `format={points}`, `privateValue={false}`; Hero only when the `^NSEI` row exists; `TILES` lacks `'^NSEI'`; IndexTile `rounded-[20px]` + `tap`, no `rounded-[16px]`. IndexPage: `<Hero` with `privateValue={false}`, `format={points}`; no `label="Level"` Stat; `52-week range`, `50-day average`, `200-day average`, `CloseLine` still present.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §3.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(market): NIFTY hero on Today; index level on the Hero [skip ci]`.

### Task 4: Market and trading leftovers

**Files:**
- Modify: `frontend/src/components/market/Sectors.jsx:~42`, `frontend/src/components/market/News.jsx:~96`, `frontend/src/components/stock/TradingChart.jsx:~118,~174`, `frontend/src/components/trading/OrderTicket.jsx:~345-346`, `frontend/src/components/trading/TradingControlBar.jsx:~111`
- Test: `frontend/src/components/market/marketIdentity.test.js` (create)

- [ ] **Step 1: Failing source test** over these five files: no `shadow-sm`, no `-wash)`, no `bg-[var(--accent)] text-[var(--surface)]`; TradingChart and News contain `text-[var(--accent-ink)]`; OrderTicket keeps `bg-[var(--text)] text-[var(--surface)]`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §4. Classes only.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `style(market): accent-ink, soft tokens, no shadow in market and trading [skip ci]`.

### Task 5: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (Market, Stock, Index sections; `verified_at`)
- Scratch: `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/market-shots.mjs`, shots in `pw/market/`

- [ ] **Step 1: Wiki** update; `verified_at` = base commit.
- [ ] **Step 2: Render** 390x844, both themes: `/market?tab=today|sectors|news|watchlist`; `/stock/RELIANCE` with and without a position; a non-INR stock; `/index/%5ENSEI`; one sector page; `/stock/RELIANCE` with hide-amounts on (set the privacy toggle's storage key; read the code). Assert `scrollWidth <= 390`. Read every PNG. Fix breaks only in Task 1-4 files, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(market): wiki for price heroes [skip ci]` (plus `fix(...): ... [skip ci]` if code changed).

## Waves

1. Tasks 1 and 4 in parallel (disjoint).
2. Tasks 2 and 3 in parallel (both consume Task 1).
3. Task 5, final review, push (Direct).
