# Lab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the admin Lab as a grouped list with live state lines, and every Lab page as a Settings-style page with a back link to Lab and no tab strip.

**Architecture:** Pure state helpers in `frontend/src/utils/lab.js` (like `utils/settings.js`); Lab home reuses an extracted `Group`; every Lab page renders through `pages/SettingsPage.jsx`, which gains `back`, `backLabel` and `right` props. Frontend only.

**Tech Stack:** React 19, Vite, react-router, Tailwind tokens, `node --test` source/unit tests.

**Spec:** `docs/superpowers/specs/2026-10-27-lab-redesign-design.md`

## Global Constraints

- Frontend only: no file under `backend/` changes.
- URLs unchanged (`/settings/lab/<page>`); add `/settings/lab/beta`.
- A failed read shows "–" (U+2013), same `DASH` as `utils/settings.js`.
- Features, endpoints and computed data of each page unchanged; only shell, navigation and ui-kit styling change.
- Tests: `cd frontend && npm test` (node --test), `npm run lint`, `npm run build`, all green before each commit.
- Commits end with `[skip ci]` (Direct deploy mode this session) and the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.
- Update `docs/wiki/frontend.md` Lab text in the commit that changes the code it describes.

## Review Focus

- `/news/accuracy` 404 before the first build: Lab row says `No report yet`, not "–".
- `/system/status` block that is `{error: ...}` counts as failing; `as_of` is not a block.
- Backlog items with status `done`/`dropped` are not "open".
- Phone width 390 px: no Lab page scrolls sideways once the tab strip is gone (Option chain table and Handbook tables scroll inside themselves).
- Non-admin opening `/settings/lab/beta` is bounced by `RequireAdmin` like the other Lab pages.

---

### Task 1: Foundations: `utils/lab.js`, shared `Group`, `SettingsPage` props

**Files:**
- Create: `frontend/src/utils/lab.js`, `frontend/src/utils/lab.test.js`, `frontend/src/components/settings/Group.jsx`
- Modify: `frontend/src/pages/SettingsHome.jsx` (import `Group` instead of the local one), `frontend/src/pages/SettingsPage.jsx`

**Interfaces:**
- Produces (`utils/lab.js`, each takes the response body or `undefined`, returns a string):
  - `strategiesState(body)`: `body.strategies[]`, live = `live_switch === true` -> `"12 strategies · 2 live"`; `[]` -> `"No strategies"`.
  - `runsState(body, now = Date.now())`: `body.runs[0].created_at` -> `"Last run today"` / `"Last run 1d ago"` / `"Last run 5d ago"` (whole days, UTC ms diff / 86400000, floor); `[]` -> `"No runs yet"`.
  - `forwardState(body)`: sum of `row.n` over `body.rows` -> `"412 scored"`; 0 -> `"Nothing scored yet"`.
  - `newsAccuracyState(body)`: `null` means 404 -> `"No report yet"`; else `"Built 27 Oct"` (`as_of`, `en-GB` day + short month, UTC) plus `" · company scan off"` when `company_scan_ok === false`.
  - `handbookState(body)`: blocks = every key except `as_of`; failing = value has `error` -> `"All checks ok"` / `"2 failing"`.
  - `backlogState(body)`: `body.items` with status not in `done|dropped` -> `"14 open"`.
  - `betaState(body)`: `"3 of 5 came back"` from `returned_from_last_week` of `active_last_week`.
  - `undefined` -> `"–"` for all.
- Produces: `Group({ title, children })` default export (markup moved verbatim from `SettingsHome.jsx`).
- Produces: `SettingsPage({ title, back = '/settings', backLabel = 'Settings', right, children })` passing `back`, `backLabel`, `right` to `PageHeader`.

- [ ] **Step 1: Write failing tests** in `utils/lab.test.js`: every helper returns `'–'` for `undefined`; the exact strings above for one normal and one empty body each; `newsAccuracyState(null) === 'No report yet'`; `handbookState({ as_of: 'x', a: {}, b: { error: 'E' } }) === '1 failing'`; `backlogState({ items: [{status:'idea'},{status:'done'},{status:'dropped'}] }) === '1 open'`; `runsState({ runs: [{ created_at: '2026-10-25T10:00:00Z' }] }, Date.parse('2026-10-27T11:00:00Z')) === 'Last run 2d ago'`.
- [ ] **Step 2: Run** `cd frontend && node --test src/utils/lab.test.js`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `utils/lab.js`, `Group.jsx`, `SettingsPage` props; `SettingsHome` imports `Group`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(lab): state helpers, shared Group, SettingsPage back/right [skip ci]`.

### Task 2: Lab home and Beta page

**Files:**
- Modify: `frontend/src/components/settings/Lab.jsx`, `frontend/src/App.jsx` (LAB map: `beta`), `frontend/src/utils/routes.js` (`LAB_PAGES` gains `'beta'`), `frontend/src/pages/SettingsHome.test.js` or new `frontend/src/components/settings/Lab.test.js`, `docs/wiki/frontend.md`
- Create: `frontend/src/pages/LabBeta.jsx`

**Interfaces:**
- Consumes: Task 1 helpers, `Group`, `SettingsPage`.
- Produces: route `/settings/lab/beta` -> `<LabBeta />` = `<SettingsPage title="Beta" back="/settings/lab" backLabel="Lab"><BetaSheet /></SettingsPage>`.

- [ ] **Step 1: Write failing source test** (`Lab.test.js`): Lab.jsx has groups `Evidence`, `Tools`, `System`; rows titled `Strategies`, `Runs`, `Forward`, `News accuracy`, `Option chain`, `Handbook`, `Backlog`, `Beta`, each `to="/settings/lab/<page>"`; does not render `<BetaSheet` inline; `LAB_PAGES` includes `'beta'`; App maps `beta`.
- [ ] **Step 2: Run** `node --test src/components/settings/Lab.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement** Lab.jsx: parallel reads on mount (`endpoints.strategyLibrary()`, `endpoints.labRuns.list` with `params: { limit: 1 }`, `endpoints.forward.scorecard`, `endpoints.newsAccuracy`, `endpoints.system.status`, `endpoints.system.backlog`, `endpoints.journal.betaMetrics`), each `.catch` leaves `undefined` except news 404 -> `null`; `live` guard on unmount; rows `ListRow` with `right={state}` and `privateValue={false}`; Option chain state `"NIFTY · BANK NIFTY"`. Add `LabBeta.jsx`, route, `LAB_PAGES`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. Expected: pass (fix `routes.test.js` expectations if it counts `LAB_PAGES`).
- [ ] **Step 5: Wiki** Lab paragraph in `docs/wiki/frontend.md`: groups, rows, state sources, Beta page.
- [ ] **Step 6: Commit** `feat(lab): grouped Lab home with state lines; Beta on its own page [skip ci]`.

### Task 3: Evidence pages (Strategies, Runs, Forward, News accuracy)

**Files:**
- Modify: `frontend/src/pages/Strategies.jsx`, `LabRuns.jsx`, `LabForward.jsx`, `NewsAccuracy.jsx`; their `*.test.js` if they assert `LAB_TABS`/`PaperShell`/`SectionTabs`; `docs/wiki/frontend.md` lines naming these pages' shells.
- Test: `frontend/src/pages/LabShell.test.js` (create; Task 4 uses its own `LabShell2.test.js` so parallel tasks never edit one file)

**Interfaces:**
- Consumes: `SettingsPage({ title, back, backLabel, right })` (Task 1).

- [ ] **Step 1: Failing test** `LabShell.test.js`: for each of the four files, source contains `<SettingsPage` and `back="/settings/lab"`, and does not contain `LAB_TABS`, `SectionTabs`, `PaperShell` or `<Layout`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement**: replace `Layout` + `PageHeader` + `SectionTabs`/`PaperShell` with `SettingsPage` (`right` takes what `PageHeader right` had: Paper badges, News accuracy rebuild control). Strategies keeps the paper notice as a `Badge kind="paper"` in `right` and keeps timeframe + `?book=` filters. Restyle leftovers to ui kit (`Card`, `ListRow`, `Empty`, `ErrorLine`, `Skeleton`, `Badge`), 44 px tap targets, wide tables in `overflow-x-auto` wrappers.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. Expected: pass.
- [ ] **Step 5: Commit** `refactor(lab): evidence pages on the Settings page shell [skip ci]`.

### Task 4: Tools and System pages (Option chain, Handbook, Backlog)

**Files:**
- Modify: `frontend/src/pages/OptionChain.jsx`, `Handbook.jsx`, `Backlog.jsx`; their `*.test.js` where they assert the old shell; `docs/wiki/frontend.md` lines naming these shells.
- Test: `frontend/src/pages/LabShell2.test.js` (create)

**Interfaces:**
- Consumes: `SettingsPage` (Task 1).

- [ ] **Step 1: Failing test** `LabShell2.test.js`: same assertions as Task 3 for these three files.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** as Task 3 (Backlog's `N open` goes to `right`). Option chain table stays inside its own horizontal scroll.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. Expected: pass.
- [ ] **Step 5: Commit** `refactor(lab): option chain, handbook, backlog on the Settings page shell [skip ci]`.

### Task 5: Cleanup and render check

**Files:**
- Modify: `frontend/src/components/layout/sections.js` (delete `LAB_TABS`); delete `components/paper/PaperShell.jsx` and `components/layout/SectionTabs.jsx` if `grep -rn` finds no importer (else keep); `docs/wiki/frontend.md`; any `frontend/src/handbook/*.md` naming `LAB_TABS`/the tab strip.
- Create: `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/lab-shots.mjs` (not committed)

- [ ] **Step 1: Failing test**: `grep -rn "LAB_TABS" frontend/src` returns nothing (add to `LabShell.test.js`: read `sections.js`, assert no `LAB_TABS`).
- [ ] **Step 2: Delete** dead exports/files; update wiki + handbook.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. Expected: pass.
- [ ] **Step 4: Render check**: Vite dev server + Playwright (Chromium), viewport 390x844, `page.route('**/api/**')` returning an admin user and sample bodies for each Lab endpoint; screenshot `/settings/lab` and each `/settings/lab/<page>` to the scratchpad; assert `document.documentElement.scrollWidth <= 390` on each.
- [ ] **Step 5: Commit** `chore(lab): drop LAB_TABS and dead shells; docs [skip ci]`.

## Waves

1. Task 1.
2. Tasks 2, 3, 4 in parallel worktrees (disjoint files; each touches a different part of `docs/wiki/frontend.md`: merge by hand on conflict).
3. Task 5, then one final review of `origin/main..main`, then push.
