# Ideas + AI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI book header on the Hero + DeltaChip; Ideas Picks grouped Engine / A / B / C(toggle); GradeTile in IdeaRow; leftover styling fixed.

**Architecture:** `pages/Ai.jsx` swaps its header div for `Hero`; `utils/ideas.js::groupByGrade` replaces `splitByEvidence` and `pages/Ideas.jsx` renders grouped sections; `IdeaRow` swaps the grade Badge for `GradeTile`; class-only fixes elsewhere.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test`, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-ideas-ai-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no new npm dependency; reuse `Hero`, `DeltaChip`, `GradeTile`, `Card`, `Badge`.
- Text on an `--accent` fill uses `--accent-ink`. Money figures keep `private`.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- `dayPct` null/undefined (no AI book yet): DeltaChip gets `pct` undefined, shows no percent, no `NaN`.
- AI book `value` null before the first fill: Hero shows `—` (Hero renders `format(value)`; `inr(null)`), no count-up from 0 to NaN.
- A pick with an unknown grade (e.g. `'D'` or missing): lands in C, IdeaRow shows no GradeTile.
- Only engine ideas, no picks (non-admin user): only the "Engine ideas" group shows; no "No proven setup" line, no C toggle.
- C toggle state survives a `fresh.reload` (state lives in Ideas, not per group).

---

### Task 1: AI book on the Hero

**Files:**
- Modify: `frontend/src/pages/Ai.jsx:65-90`, `frontend/src/components/ai/{Scoreboard,Positions,Activity}.jsx` (settings link classes only), `frontend/src/pages/Ai.test.js`

**Interfaces:**
- Consumes: `Hero({ label, value, change, children })`, `DeltaChip({ value, pct, suffix })`.

- [ ] **Step 1: Failing tests** in `Ai.test.js`: imports `Hero` and `DeltaChip`; `label="AI book"`; `dayPct * 100` guarded by `typeof dayPct === 'number'`; `suffix="today"`; no `rounded-[16px]`; still contains `Autopilot on`, `cap deployed`, `Lab off`, `Paused on paper`, `<StopAi`, `/settings/autopilot`; loading uses `Skeleton`. In `components/ai/{Scoreboard,Positions,Activity}.jsx`: no `text-[var(--surface)]` next to `bg-[var(--accent)]`; contains `text-[var(--accent-ink)]`. Update any existing Ai.test assertion pinned to the old header markup.
- [ ] **Step 2: Run** `cd frontend && node --test src/pages/Ai.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §1 and §4 (first bullet).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(ai): AI book on the Hero with a today chip [skip ci]`.

### Task 2: Ideas grouped by grade

**Files:**
- Modify: `frontend/src/utils/ideas.js:72-76` (replace `splitByEvidence` with `groupByGrade`), `frontend/src/utils/ideas.test.js:42,150-160`, `frontend/src/pages/Ideas.jsx`, `frontend/src/pages/Ideas.test.js`

**Interfaces:**
- Produces: `groupByGrade(items: Idea[]) -> { engine: Idea[], A: Idea[], B: Idea[], C: Idea[] }` (input order kept; `engine` = `kind !== 'p'`; C = picks graded C or with no/unknown grade).

- [ ] **Step 1: Failing tests**:
  - `ideas.test.js`: `groupByGrade([{kind:'s',id:1},{kind:'p',grade:'B',id:2},{kind:'p',grade:'A',id:3},{kind:'p',id:4},{kind:'p',grade:'C',id:5},{kind:'p',grade:'D',id:6}])` deep-equals engine ids `[1]`, A `[3]`, B `[2]`, C `[4,5,6]`; `groupByGrade([])` gives four empty arrays. Remove the `splitByEvidence` test and import.
  - `Ideas.test.js`: uses `groupByGrade`, not `splitByEvidence`; contains `Engine ideas`, `GRADES.A.label`, `GRADES.B.label`; keeps `aria-expanded={showUnproven}` and `grade C: no edge yet`; the "No proven setup" line is conditioned on engine, A and B all empty and C non-empty.
- [ ] **Step 2: Run** `node --test src/utils/ideas.test.js src/pages/Ideas.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §2. One small local `Group` render helper inside Ideas.jsx is fine (header + rows); no new file.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(ideas): picks grouped Engine, A, B, then C [skip ci]`.

### Task 3: GradeTile in IdeaRow; soft pills

**Files:**
- Modify: `frontend/src/components/ideas/IdeaRow.jsx` (imports, `NEWS` map lines ~18-19, row link ~78-88), `frontend/src/components/suggestions/SuggestionRecord.jsx:~253`
- Test: `frontend/src/components/ideas/ideaRowIdentity.test.js` (create)

- [ ] **Step 1: Failing source test**: IdeaRow imports `GradeTile`; renders `<GradeTile grade={idea.grade}` guarded by `GRADES[idea.grade]`; no `<Badge kind={GRADES[`; no `-wash)` in IdeaRow or SuggestionRecord; `--gain-soft` and `--loss-soft` present in IdeaRow.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §3 and §4 (second bullet). GradeTile is the first child inside the row `Link`, `shrink-0`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `style(ideas): grade tile on idea rows, soft news pills [skip ci]`.

### Task 4: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (AI and Ideas sections; `verified_at`)
- Scratch (not committed): `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/ideas-ai-shots.mjs`, shots in `pw/ideas-ai/`

- [ ] **Step 1: Wiki** update; `verified_at` = base commit.
- [ ] **Step 2: Render**: reuse earlier `pw/*-shots.mjs` mocks; 390x844, both themes: `/ai?tab=scoreboard|positions|activity` (autopilot on), `/ai` autopilot off; `/ideas` with engine+A+B+C (C expanded once), only C, empty; `/ideas?tab=holdings`. Assert `scrollWidth <= 390`. Read every PNG. Fix breaks only in Task 1-3 files, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(ideas): wiki for grouped ideas and the AI hero [skip ci]` (plus `fix(...): ... [skip ci]` if code changed).

## Waves

1. Tasks 1, 2, 3 in parallel worktrees (disjoint files).
2. Task 4, final review, push (Direct).
