# Detail Pages Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Hero per detail page for its main figure (closed trades, strategy net, weekly return), GradeTile + chip on IdeaDetail, leftovers in Strategies and Doc.jsx fixed.

**Architecture:** Pages adopt existing `Hero` / `DeltaChip` / `GradeTile` (with `privateValue` and `format` from sub-project 5) behind data guards; class-only fixes elsewhere.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test`, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-detail-pages-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no new npm dependency; reuse `Hero`, `DeltaChip`, `GradeTile`, `Stat`, `Card`.
- Own money (trade P&L, AI book net) stays `private`; percent returns and forecasts use `privateValue={false}`.
- Text on an `--accent` fill uses `--accent-ink`.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- Open trade (RoundTrip `trip.pnl === null`, AiTrade `s.open`): no Hero, "Open" still shown, nothing missing.
- Closed trade with P&L exactly 0: Hero shows `₹0` (no sign), no crash.
- AiStrategy record still loading / errored / empty: Card states as today, no Hero flash.
- WeeklyReport `r.you.ret == null`: "No curve" Empty with Connect link, no Hero.
- IdeaDetail pick without `expectedMedian`: Expected return Card absent as today; unknown grade: no tile.

---

### Task 1: Trade pages (RoundTrip, AiTrade)

**Files:**
- Modify: `frontend/src/pages/RoundTrip.jsx` (`Body`), `frontend/src/pages/AiTrade.jsx:~78-92`
- Test: `frontend/src/pages/tradeHero.test.js` (create)

- [ ] **Step 1: Failing source tests**: RoundTrip imports `Hero`; `<Hero label="P&L"` guarded by `trip.pnl !== null`; `format={signedInr}` (or inline `(v) => inr(v, { sign: true })`); P&L `Stat` only in the open branch, still `'Open'`; `private` wrappers on Average entry/exit kept; `View stock` and `<NewsChips` kept. AiTrade imports `Hero`; `<Hero label="Net"` guarded by `!s.open`; no `label="Net"` Stat; `Gross`, `Costs`, `Exit reason`, `Open ${...}` link kept; no `privateValue={false}` in either file.
- [ ] **Step 2: Run** `cd frontend && node --test src/pages/tradeHero.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §1.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(trades): closed trade P&L on the Hero [skip ci]`.

### Task 2: Summary pages (AiStrategy, WeeklyReport)

**Files:**
- Modify: `frontend/src/pages/AiStrategy.jsx:~49-61`, `frontend/src/pages/WeeklyReport.jsx:~21,~99-108`, `frontend/src/pages/WeeklyReport.test.js`
- Test: `frontend/src/pages/AiStrategy.test.js` (create)

- [ ] **Step 1: Failing source tests**: AiStrategy `<Hero label="Net · paper"` only in the `row` branch, children grid `grid-cols-3` with `Open`, `vs NIFTY`, `Win rate`; "Paper record" Card still wraps loading/error/"No trades yet". WeeklyReport `<Hero label="Your account this week"` with `privateValue={false}` and `format={signedPct}` (or inline), guarded by `r.you.ret != null`; children `NIFTY` and `Excess` Stats; "No curve for this week" Empty and `/settings/brokers` link kept; `act` uses `text-[var(--accent-ink)]`, no `text-[var(--surface)]`. Update existing WeeklyReport test assertions pinned to the old 3-Stat card.
- [ ] **Step 2: Run** `node --test src/pages/AiStrategy.test.js src/pages/WeeklyReport.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §2 (first two bullets).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(reports): strategy net and weekly return on the Hero [skip ci]`.

### Task 3: IdeaDetail

**Files:**
- Modify: `frontend/src/pages/IdeaDetail.jsx` (`Fold` ~44, badge row ~152, Expected return ~214-218), `frontend/src/pages/IdeaDetail.test.js`

- [ ] **Step 1: Failing source tests**: imports `GradeTile` and `DeltaChip`; `<GradeTile grade={idea.grade}` behind `GRADES[idea.grade]`; no `<Badge kind={GRADES[`; `<DeltaChip pct={idea.expectedMedian * 100}` with `privateValue={false}`; no `text-[24px]`; `Fold` uses `rounded-[20px]`, no `rounded-[16px]`; `idea.when`, `idea.rupees`, `Range ` lines kept.
- [ ] **Step 2: Run** `node --test src/pages/IdeaDetail.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §2 (third bullet).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `style(ideas): grade tile and forecast chip on the idea page [skip ci]`.

### Task 4: Strategies and Doc kit leftovers

**Files:**
- Modify: `frontend/src/pages/Strategies.jsx:~87,~94`, `frontend/src/components/doc/Doc.jsx:~233,~240,~277,~281`
- Test: `frontend/src/components/doc/docIdentity.test.js` (create)

- [ ] **Step 1: Failing source test** over both files: no `rounded-[16px]`, no `border-dashed`, no `-wash)`, no `shadow-sm`, no `bg-[var(--accent)] text-[var(--surface)]`; Doc count badge contains `text-[var(--accent-ink)]`; Doc chips contain `--gain-soft` and `--loss-soft`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §3. Classes only.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS (update `Strategies.test.js` if it pins 16 px).
- [ ] **Step 5: Commit** `style(doc): Strategies and Doc kit on the identity [skip ci]`.

### Task 5: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (detail page sections; `verified_at`)
- Scratch: `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/detail-shots.mjs`, shots in `pw/detail/`

- [ ] **Step 1: Wiki** update; `verified_at` = base commit.
- [ ] **Step 2: Render** 390x844, both themes: `/money/trade/:id` open + closed; `/ai/trade/:id` open + closed; `/ai/strategy/:name` with trades + empty; `/reports/weekly` with curve + without; `/ideas/:id` graded pick with forecast; `/settings/lab/strategies` or wherever `Strategies` routes (check App.jsx). Assert `scrollWidth <= 390`. Read every PNG. Fix breaks only in Task 1-4 files, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(detail): wiki for detail page heroes [skip ci]` (plus `fix(...): ... [skip ci]` if code changed).

## Waves

1. Tasks 1, 2, 3, 4 in parallel (disjoint files).
2. Task 5, final review, push (Direct).
