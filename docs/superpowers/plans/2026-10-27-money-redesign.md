# Money Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Money's headline becomes the Hero + DeltaChip with a 2-stat strip; leftover old styling in Money's files and the `sheet` utility goes; tabs unchanged.

**Architecture:** `pages/Money.jsx` swaps its headline Card for the existing `Hero`/`DeltaChip`; class-only fixes in `index.css` (utility source) and three Money component files.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test` source tests, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-money-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no new npm dependency; reuse `Hero`, `DeltaChip`, `Stat`, `Badge`, `Card`.
- Text on an `--accent` fill uses `--accent-ink`. Money figures keep `private`.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- `h.day_change` null/undefined (fresh account, no price yet): DeltaChip renders neutral, no `NaN`, no crash.
- `h.pnl_pct` / `h.xirr` null: Stats show what they show today (`formatXirr` handles null).
- Stale holdings: badge still shows and sits above the stats strip inside the Hero.
- Hide-amounts: Hero value, chip, "Put in" rupees all blurred.
- Holdings verdict filter Chips (`onCls` = gain/loss/warn/muted fill) stay readable with `--accent-ink` text in both themes.

---

### Task 1: Money top on the Hero

**Files:**
- Modify: `frontend/src/pages/Money.jsx:60-90`, `frontend/src/pages/Money.test.js`

**Interfaces:**
- Consumes: `Hero({ label, value, format, change, children, to })`, `DeltaChip({ value, pct, suffix })` from `components/ui/`.

- [ ] **Step 1: Failing tests** in `Money.test.js`: imports `Hero` and `DeltaChip`; `<Hero` source contains `label="Your broker account"` and `suffix="today"`; no `label="Today"`; `Total P&L` and `Yearly (XIRR)` present; Connect link uses `text-[var(--accent-ink)]` and no `text-[var(--surface)]`; `<span className="private">` on the Put-in rupees. Update the existing stale test: `holdingsStale(` index < index of `Total P&L` (was `figure-lg`).
- [ ] **Step 2: Run** `cd frontend && node --test src/pages/Money.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §1. Error/loading/Empty stay inside `<Card>`; only the `h` branch renders `Hero` (outside any Card). Stats grid `grid grid-cols-2 gap-3 mt-3`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(money): headline on the Hero with a today chip [skip ci]`.

### Task 2: Leftovers at the source and in Money files

**Files:**
- Modify: `frontend/src/index.css` (`@utility sheet`, `@utility doc-meta` comment), `frontend/src/components/money/JournalTab.jsx:~276`, `frontend/src/components/money/HoldingsTab.jsx` (lines ~35-36, ~60, ~170, ~212-228), `frontend/src/components/portfolio/Rebalance.jsx:~284`
- Test: `frontend/src/components/money/moneyIdentity.test.js` (create)

- [ ] **Step 1: Failing source test**: `index.css` `@utility sheet` block has `border-radius: 20px`; `doc-meta` comment no longer says "typewriter"; across `components/money/*.jsx` and `components/portfolio/Rebalance.jsx`: no `rounded-[16px]`, no `rounded-t-[16px]`, no `border-dashed`, no `-wash)`, no `bg-[var(--accent)] text-[var(--surface)]`; HoldingsTab Chip on-state contains `text-[var(--accent-ink)]`; Rebalance still contains `bg-[var(--text)] text-[var(--surface)]` (rule toggle untouched).
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §2. Classes only.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS (update any existing test pinning `-wash` or 16 px in these files).
- [ ] **Step 5: Commit** `style(money): sheets at 20px, soft verdict pills, accent-ink [skip ci]`.

### Task 3: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (Money section: Hero + DeltaChip on top, 2-stat strip; `verified_at`)
- Scratch (not committed): `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/money-shots.mjs`, shots in `pw/money/`

- [ ] **Step 1: Wiki** update; `verified_at` = base commit.
- [ ] **Step 2: Render**: reuse `pw/identity-shots.mjs` / `pw/home-shots.mjs` mocks; 390x844, both themes; `/money?tab=overview|holdings|tax|journal` with a populated account (holdings with SELL/ADD verdicts, tax rows, journal rows) and `/money` with no headline (Empty). Assert `scrollWidth <= 390`. Read every PNG. Fix breaks only in Task 1-2 files, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(money): wiki for the Money hero [skip ci]` (plus `fix(money): ... [skip ci]` if code changed).

## Waves

1. Tasks 1 and 2 in parallel worktrees (disjoint files).
2. Task 3, final review, push (Direct).
