# Visual Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give NeoTrade the dark-first deep-emerald "Glow card" identity: new tokens and type, restyled primitives and chrome, and the Hero / DeltaChip / GradeTile components, proven on Home's top block.

**Architecture:** Token values change in `frontend/src/index.css` under the existing names, so every component follows; primitives in `components/ui/` are restyled without prop changes; three new components join `components/ui/`. Motion is CSS classes in `index.css` plus one rAF count-up in `Hero`.

**Tech Stack:** React 19, Vite, Tailwind v4 (`@tailwindcss/postcss`), CSS custom properties, `node --test` source/unit tests, Playwright (scratch only) for screenshots.

**Spec:** `docs/superpowers/specs/2026-10-27-visual-identity-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data the UI has today stays; nothing is removed or hidden. Choose the simplest implementation and the simplest-looking result (no extra decoration, no new wrappers or abstractions beyond the three named components).
- Frontend only; no new npm dependency (Playwright lives only in the scratchpad, never in package.json).
- Token names unchanged; values exactly as the spec's table. New tokens: `--accent-ink`, `--glow`, `--gain-soft`, `--loss-soft`, `--fs-12/13/15/17/22/28/44`.
- `--accent` never colours a number; gains/losses carry ▲/▼ or a sign.
- Font: Geist 400/500/600/700/800 from Google Fonts; fallback `ui-sans-serif, system-ui, sans-serif`.
- Radius: 12 controls, 20 cards, 28 hero, 999 pills. No box shadows in dark.
- Motion off under `prefers-reduced-motion: reduce`.
- Primitive props unchanged (no caller edits needed outside the files a task lists).
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Existing users with a stored `light` choice keep light; only users with no stored choice get dark.
- Light theme still readable: `--text-muted`, `--gain`, `--loss` ≥ 4.5:1 on light `--surface` (contrast test covers both themes).
- `private` class (hide-amounts blur) still on every money figure inside `Hero` and `DeltaChip`.
- Hero count-up never shows a wrong final value: after the animation (and immediately under reduced motion) the text equals `format(value)`; a later `value` change (refresh) renders directly with no animation.
- Primary buttons stay readable: `--accent-ink` on `--accent` ≥ 4.5:1 in both themes (contrast test).

---

### Task 1: Tokens, type, theme default, motion classes

**Files:**
- Modify: `frontend/src/index.css` (font `@import`, `--font-sans`, both theme blocks, new tokens, motion classes), `frontend/src/context/ThemeContext.jsx:12-14`, `frontend/index.html:29` (comment naming Archivo)
- Create: `frontend/src/theme.test.js`

**Interfaces:**
- Produces CSS: tokens above; `.tap` (transition transform 120ms ease-out; `:active` scale(.98)); `.fade-in` (150ms opacity 0→1 keyframe `nt-fade`); `.hero-num` (44px/800/-0.04em/line-height 1/tabular-nums); all transitions/animations disabled in a `prefers-reduced-motion: reduce` block.
- Produces: `ThemeContext` initial theme = stored `'light'|'dark'` else `'dark'`.

- [ ] **Step 1: Failing tests** `theme.test.js`: parse `index.css` for each theme block (dark and light, as the file defines them) and assert, with a WCAG relative-luminance helper in the test: `--text` and `--text-muted` ≥ 4.5 on `--bg`, `--surface`, `--surface-2`; `--gain`, `--loss` ≥ 4.5 on `--surface`; `--accent-ink` ≥ 4.5 on `--accent`. Assert exact dark values `--bg:#07100c`, `--accent:#10b981`, `--gain:#3ddc97`, `--loss:#ff6b6b`; `--font-sans` starts with `"Geist"`; `ThemeContext.jsx` has no `prefers-color-scheme` fallback and returns `'dark'`; `.tap` and a `prefers-reduced-motion` block exist.
- [ ] **Step 2: Run** `cd frontend && node --test src/theme.test.js`. Expected FAIL.
- [ ] **Step 3: Implement.** Keep the existing light/dark selector structure of `index.css` (read it first); only values and new tokens change. Chart/heat tokens unchanged; old aliases still mapped. If a spec value fails the contrast test, adjust lightness minimally, keep the hue, and note it in the report.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. Expected PASS (fix any existing test pinned to old hex values by updating it to the new value).
- [ ] **Step 5: Commit** `feat(design): emerald dark-first tokens, Geist, motion classes [skip ci]`.

### Task 2: Primitives restyle

**Files:**
- Modify: `frontend/src/components/ui/{Card,Tile,Stat,ListRow,Badge,Button,Tabs,PageHeader,Empty,Skeleton,ErrorLine}.jsx`; their existing `*.test.js` where they pin old classes
- Test: `frontend/src/components/ui/identity.test.js` (create)

**Interfaces:**
- Consumes (Task 1): tokens, `.tap`, `.fade-in`.
- Produces: same exports and props as today.

- [ ] **Step 1: Failing source test** `identity.test.js`: `Card` uses `rounded-[20px]`; `Button` primary uses `bg-[var(--accent)]` and `text-[var(--accent-ink)]`, `min-h-11`, `rounded-[12px]`, `tap`; `ListRow` linked/button rows carry `tap`; `Badge` uses `rounded-full`; `Tabs` panels or active content carry `fade-in`; `PageHeader` title `text-[22px]` + `tracking-[-0.02em]`; no file in `components/ui/` contains `shadow-` or `rounded-[16px]`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §3 (Tabs = segmented pill: active `--surface` on `--surface-2` track; Skeleton shimmer in `--surface-2`).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(design): primitives on the emerald identity [skip ci]`.

### Task 3: Hero, DeltaChip, GradeTile; Home hero

**Files:**
- Create: `frontend/src/components/ui/{Hero,DeltaChip,GradeTile}.jsx`, `frontend/src/components/ui/signature.test.js`
- Modify: `frontend/src/components/home/HeroRow.jsx` (also drop its duplicated `if (failed …)` line), `frontend/src/pages/Home.test.js` if it pins HeroRow markup

**Interfaces:**
- Consumes (Task 1): `--glow`, `--gain-soft`, `--loss-soft`, `--accent-ink`, `.hero-num`, `.tap`.
- Produces:
  - `Hero({ label, value, format = inr, change, children, to })`: number `value`, text = `format(value)`; count-up 0→value over 600ms ease-out on first mount only, skipped under reduced motion (`matchMedia('(prefers-reduced-motion: reduce)')`); `to` renders a `Link` with `tap`; radius 28, `background: var(--glow)`; value carries `private`.
  - `DeltaChip({ value, pct, suffix })`: `value` rupees, `pct` percent units (1.65 = 1.65%, formatted via `pct(p / 100, { sign: true })`), `suffix` string; ▲ for >0, ▼ for <0, neutral (no arrow, `--surface-2`) for 0; `private`.
  - `GradeTile({ grade })`: `'A'|'B'|'C'`, `aria-label="Grade A"`.
- [ ] **Step 1: Failing tests** `signature.test.js` (source + pure): Hero uses `var(--glow)`, `rounded-[28px]`, `hero-num`, `private`, `prefers-reduced-motion`, `requestAnimationFrame`; DeltaChip shows `▲` / `▼`, uses `--gain-soft` / `--loss-soft`, has a zero branch with `--surface-2`, `private`; GradeTile maps A→`--accent` + `--accent-ink`, B→`--surface-2`, C→`--border` and sets `aria-label={\`Grade ${grade}\`}`; HeroRow imports `Hero` and `DeltaChip` and keeps the NIFTY gap line and `meta` line.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** the three components; HeroRow renders `<Hero to="/money" label="Your account" value={headline.value} change={<DeltaChip value={headline.day_change} pct={headline.day_change_pct} suffix={day.toLowerCase()} />}>` with the NIFTY/gap and meta lines as children. Empty/error branches unchanged.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(design): Hero, DeltaChip, GradeTile; Home hero [skip ci]`.

### Task 4: Chrome (Header, BottomTabs, SideRail)

**Files:**
- Modify: `frontend/src/components/layout/{Header,BottomTabs,SideRail}.jsx`, `frontend/src/components/layout/Header.test.js` (append)

**Interfaces:**
- Consumes (Task 1): tokens, `.tap`. `MarketDot` logic unchanged (dot green only when socket `live`).

- [ ] **Step 1: Failing test** (append to `Header.test.js`, plus same file reads BottomTabs/SideRail): logo text `NeoTrade` at `text-[18px]` `font-bold`; BottomTabs and SideRail active item uses `text-[var(--accent)]`, inactive `text-[var(--text-muted)]`, bar `bg-[var(--surface)]` with `border-[var(--border)]`; tab links carry `tap`; existing MarketDot assertion still passes.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(design): header and nav on the emerald identity [skip ci]`.

### Task 5: Docs, render check, leftover list

**Files:**
- Modify: `DESIGN.md` (rewrite to spec §1-4), `docs/wiki/frontend.md` (Design tokens section, new components in the ui row, `verified_at`)
- Create (scratch, not committed): screenshots + script under `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/` (Playwright already installed there; reuse `lab-shots.mjs` mocking approach)

- [ ] **Step 1: Rewrite** `DESIGN.md` and the wiki sections.
- [ ] **Step 2: Render**: `npm run build && npx vite preview`, Playwright 390x844, mocked `/api/**` (admin user, sample bodies), both themes (set the theme storage key `ThemeContext` reads), screenshots of `/`, `/money`, `/ideas`, `/ai`, `/market`, `/settings`; assert `scrollWidth <= 390` each. Fix any visual break in files owned by Tasks 1-4 (that is in scope) and re-shoot.
- [ ] **Step 3: Leftover list**: `grep -rln "doc-meta\|border-dashed\|--paper\|--ink\|--stamp\|rounded-\[16px\]\|shadow-" frontend/src --include=*.jsx` → write the file list, grouped by sub-project 2-7, into the report (not the repo).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `docs(design): DESIGN.md and wiki for the emerald identity [skip ci]`.

## Waves

1. Task 1.
2. Tasks 2, 3, 4 in parallel worktrees (disjoint files).
3. Task 5, final review, push.
