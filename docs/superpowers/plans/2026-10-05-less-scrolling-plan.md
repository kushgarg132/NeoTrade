# Less Scrolling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every measured page ≤ 1.5 phone screens (stock page ≤ 2.2) by folding, not removing.

**Architecture:** Four shared fixes: compact `Row` (settings), one-row strategy lists, capped/collapsible lists, `Statement inline` + one-line figures. Frontend only.

**Tech Stack:** React 19, Tailwind 4, Vite. **Spec:** `docs/superpowers/specs/2026-10-05-less-scrolling-design.md`

## Global Constraints

- No information removed; anything hidden is one tap away with `aria-expanded` on its toggle.
- `Statement` without `inline` behaves exactly as today.
- Verification per task: `cd frontend && npm run build && npx eslint <changed files>` (0 new errors). No component test harness exists; the binding check is the post-deploy re-measurement (Task 5).

## Review Focus

1. **A hint toggle inside a clickable row** (StrategyReadiness/EngineSettings rows that also expand) → hint tap must not also toggle the row.
2. **Keyboard users** → every new toggle is a `<button>`, reachable by Tab, Enter/Space toggles.
3. **Action-plan Markdown with no recognised headings** → clamped render with `Show all`, never empty.
4. **`Statement inline` with a long first cell (long index or headline names)** → truncates, values never wrap under it.
5. **A proposal with an option contract** → option terms reachable behind `Why`, Approve buttons unchanged.

---

### Task 1: Compact setting row
**Files:** `frontend/src/components/settings/Fields.jsx`.
- [ ] `Row`: one line (no `flex-wrap`), `py-2`, hint `line-clamp-1` with a button toggle when longer than 60 chars; `NumberField` `w-24`.
- [ ] Build + lint. Commit `fix(ui): compact settings rows on phone`.

### Task 2: One-row strategy lists
**Files:** `frontend/src/components/paper/EngineSettings.jsx`, `frontend/src/components/paper/StrategyReadiness.jsx`.
- [ ] Rule sentence once (spec copy); each strategy one row: name · short status (`backtest ✓/✗/–` · `{d}/20 days` · `{t}/30 trades` or `ready`, derived from the fields each component already reads) · existing control; tap expands to today's text + backtest link; one open at a time.
- [ ] Build + lint. Commit `fix(ui): one row per strategy, the go-live rule once`.

### Task 3: Capped and collapsible lists
**Files:** `frontend/src/pages/Portfolio.jsx`, `frontend/src/pages/MyPortfolio.jsx` (+ small `PlanGroups` helper in the same file), `frontend/src/components/suggestions/SuggestionRecord.jsx`.
- [ ] Executions latest 10 + `Show all {n}`.
- [ ] Action plan split into collapsible groups (first open, bullet count), fallback clamp + `Show all`.
- [ ] SuggestionRecord collapsed card per spec; thesis/reasons/option terms behind `Why` (closed).
- [ ] Build + lint. Commit `fix(ui): cap executions, fold the action plan and proposal details`.

### Task 4: One-line figures
**Files:** `frontend/src/components/doc/Doc.jsx` (`Statement inline`), `frontend/src/index.css`, `frontend/src/components/dashboard/Market.jsx`, `frontend/src/components/analysis/Fundamentals.jsx`, `frontend/src/components/analysis/TradingLevels.jsx`.
- [ ] `Statement inline` → class `statement-inline`; phone CSS: row as flex, first cell `flex-1 min-w-0 truncate`, others right-aligned, no captions.
- [ ] Market Indices/Movers `inline`; Indian indices first 4, world behind `World ›`.
- [ ] Fundamentals `inline` in `grid sm:grid-cols-2` per group; TradingLevels one line per level.
- [ ] Build + lint. Commit `fix(ui): one line per figure on phone`.

### Task 5: Deploy and re-measure
- [ ] Push (direct mode: `[skip ci]` on HEAD); wait for the Vercel production build to be READY.
- [ ] Re-run the measurement (fresh 15-minute owner token in a private scratch file, deleted after) for every page in the spec table; report before/after; any page over target is reported with its tallest section.
