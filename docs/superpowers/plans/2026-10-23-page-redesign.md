# Page-by-page redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the content of all 18 pages for a fast-scanning Indian equities trader and a new user, on one shared chart/density foundation.

**Architecture:** Wave 0 adds chart tokens, `chartTheme.js`, a dense `ListRow` and an uncommitted screenshot harness to branch `redesign/pages`. Waves 1–2 run page lanes in parallel, each a Sonnet subagent in its own worktree, one commit per page, merged back in lane order.

**Tech Stack:** React 19, Vite 8, Tailwind 4, recharts 3, lucide-react, `node --test`, Playwright (Python) for screenshots.

**Spec:** `docs/superpowers/specs/2026-10-23-page-redesign-design.md`

## Global Constraints

- No new dependencies. Charts: `recharts`. Icons: `lucide-react`.
- No backend or API changes; no edits under `docs/` from lanes.
- Shared folders read-only to lanes: `components/ui/`, `components/common/`, `components/doc/`, `components/layout/`, `src/index.css`.
- Mine figures labelled as the trader's own broker account; every AI / Picks / strategy figure carries the Paper label until live.
- No advice wording ("you should buy", "we recommend"). Verdicts are the engine's, worded as the engine's.
- Picks stay admin-only (existing gate unchanged).
- Keep: per-page fetching, `useTopic`/`useRefetchOn`, `private` class on the user's money, the second-tap order flow, `?tab=` URLs.
- Tokens only, no raw hex in components. Nothing functional below 12 px. Touch targets 44 px (dense rows 36 px, list only, never a lone button).
- Gate per page: `cd frontend && npm run build && npm test` both green.
- STRICT no push. Commit subject `feat(ui/<page>): …`, body lists the five fixes, ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Empty account** (no broker connected, no holdings, no ideas): every section shows an Empty naming the action that fills it, never a blank card or `₹0.00` that reads as real. Lanes shoot the empty fixture.
2. **Dark mode charts**: series and heatmap cells stay distinguishable on `--surface` dark. Covered by the dataviz validator in Task 1.
3. **Hide-amounts on**: every new money figure on Mine regions blurs. Each lane asserts `private` on new money elements in its page test.
4. **Long symbols / 390 px**: `BAJAJFINSV`, `M&M` and 7-figure rupee values truncate, never overflow horizontally. Checked in each 390 px screenshot.
5. **Paper vs Mine confusion**: a figure from the AI account never appears without its Paper label. Each lane's page test asserts the label is present in the source near AI figures.

---

### Task 1 (Wave 0, inline): Chart tokens and `chartTheme.js`

**Files:**
- Modify: `frontend/src/index.css` (`:root` and `.dark` blocks), `DESIGN.md` (tokens table)
- Create: `frontend/src/components/ui/chartTheme.js`, `frontend/src/components/ui/chartTheme.test.js`
- Modify: `frontend/src/components/money/ValueChart.jsx`, `frontend/src/components/mine/ValueCurve.jsx` (adopt the theme)

**Interfaces:**
- Produces: CSS vars `--chart-1` … `--chart-6`, `--heat-neg-3` … `--heat-neg-1`, `--heat-0`, `--heat-pos-1` … `--heat-pos-3`.
- Produces: `chartTheme.js` exports `AXIS` (props for `XAxis`/`YAxis`: `tick {fontSize:12, fill:'var(--text-muted)'}`, `tickLine:false`, `axisLine {stroke:'var(--border)'}`), `GRID` (`{stroke:'var(--border)', vertical:false}`), `SERIES` (array of the six `var(--chart-n)` strings), `heatColor(pct: number, maxAbs = 3): string` returning a `var(--heat-…)` string, and `TOOLTIP_STYLE` (surface bg, border, radius 12, 13 px text).

- [ ] Step 1: Load the dataviz skill, then pick the categorical and diverging values with its validator for both themes. Gain/loss ends of the heat ramp derive from `--gain`/`--loss`.
- [ ] Step 2: Write `chartTheme.test.js`: `heatColor(0) === 'var(--heat-0)'`, `heatColor(5) === 'var(--heat-pos-3)'`, `heatColor(-0.5) === 'var(--heat-neg-1)'`, `heatColor(NaN) === 'var(--heat-0)'`, `SERIES.length === 6`, and every var used in the file is defined in `index.css` (read the file as text).
- [ ] Step 3: Run `npm test`. Expected: FAIL (module missing).
- [ ] Step 4: Add the vars, `chartTheme.js`, the DESIGN.md rows; switch the two charts to `AXIS`/`GRID`.
- [ ] Step 5: `npm run build && npm test`. Expected: both pass.
- [ ] Step 6: Commit `feat(ui): chart tokens and shared recharts theme`.

### Task 2 (Wave 0, inline): Dense `ListRow`

**Files:** Modify `frontend/src/components/ui/ListRow.jsx`; Create `frontend/src/components/ui/ListRow.test.js`.

**Interfaces:** Produces `ListRow` prop `dense?: boolean` (default `false`): `min-h-9 py-1`, title 14 px, sub 12 px, right 14 px. Default rendering unchanged.

- [ ] Step 1: Write `ListRow.test.js` (source-contract style, like `Tile.test.js`): asserts `dense` in the props, `min-h-9` only on the dense branch, `min-h-14` still the default.
- [ ] Step 2: Run, expect FAIL. Implement. Run `npm run build && npm test`, expect PASS.
- [ ] Step 3: Commit `feat(ui): dense ListRow for trader lists`.

### Task 3 (Wave 0, inline): Cross-page critique and screenshot harness

**Files (not committed):** `.superpowers/sdd/2026-10-23-page-redesign/critique.md`, `shots.py`, `fixtures/<page>.full.json`, `fixtures/<page>.empty.json`.

**Interfaces:** Produces `python3 shots.py --page <Name> --route <path> [--fixture full|empty] --out <dir>`: runs `vite preview` on a free port against the worktree's `dist/`, routes `**/api/v1/**` to the fixture map (URL path → JSON; unmatched → `{}` with 200), stubs `/auth/me` as `{id:'u1', email:'a@b.c', name:'K', role:'admin'}`, sets `localStorage.neotrade_token`, and saves `<out>/<page>-<fixture>-<390|1280>-<light|dark>.png`. Dark via `localStorage` theme key used by the app (read `hooks/` for the key name). WebSocket 403s are expected and ignored.

- [ ] Step 1: impeccable (critique mode) over the current app: findings that apply across pages go in `critique.md`, plus one short section per page with first-pass observations.
- [ ] Step 2: Write `shots.py` and fixtures (full fixtures from the real response shapes in `utils/api.js` callers; empty fixtures return empty lists / nulls).
- [ ] Step 3: Shoot Home full + empty at both widths and themes. Expected: 8 PNGs, Home renders data.

### Task 4 (Waves 1–2, subagents): One page

Template run once per page, inside its lane. Lanes and owned folders are the spec's table.

**Files:** Modify `frontend/src/pages/<Page>.jsx` and files in the lane's owned folders only. Create or extend `frontend/src/pages/<Page>.test.js` (source-contract tests).

**Interfaces:** Consumes Task 1 (`AXIS`, `GRID`, `SERIES`, `heatColor`, `TOOLTIP_STYLE` from `components/ui/chartTheme`), Task 2 (`ListRow dense`), Task 3 (`shots.py`, `critique.md`).

- [ ] Step 1: Read the page, its components, `critique.md`, and its fixture. Shoot the "before" set.
- [ ] Step 2: Critique as the trader (scan speed, density, P&L/risk visible, clicks to act) and as the new user (purpose, empty states, plain words). Rank the top 5 fixes by impact.
- [ ] Step 3: Write `<Page>.test.js` asserting the fixes that are checkable in source (e.g. Paper label present near AI figures, `private` on new money figures, Empty with an action for each data section, chart uses `AXIS`). Run `npm test`, expect the new assertions to FAIL.
- [ ] Step 4: Implement the five fixes.
- [ ] Step 5: `npm run build && npm test`. Expected: both pass.
- [ ] Step 6: Shoot "after" (full + empty, 390 + 1280, light + dark). Look at every PNG: no horizontal overflow at 390, dark legible.
- [ ] Step 7: Commit `feat(ui/<page>): …` with the five fixes in the body.
- [ ] Step 8: Report: the five fixes, shared-folder changes needed (file + exact change), screenshot paths.

### Task 5 (inline, between and after waves): Merge and shared changes

- [ ] Step 1: Record `git rev-parse origin/main` before each wave; after it, confirm unchanged.
- [ ] Step 2: Merge lane branches into `redesign/pages` in lane order; on conflict, resolve keeping both lanes' intent.
- [ ] Step 3: Apply queued shared-folder changes; `npm run build && npm test`.
- [ ] Step 4: After wave 2: update `docs/wiki/frontend.md` (changed sections, `verified_at`) and `DESIGN.md` if a pattern became shared; commit `docs(wiki): frontend after page redesign`.

### Task 6 (inline): Final review and ship

- [ ] Step 1: Dispatch impeccable:impeccable-finish-reviewer over `main..redesign/pages` with the spec and `critique.md`.
- [ ] Step 2: Fix material findings; gate; commit `fix(ui): finish-review fixes`.
- [ ] Step 3: Ask the deploy mode (AskUserQuestion), then merge `redesign/pages` into `main` and push per the answer.
