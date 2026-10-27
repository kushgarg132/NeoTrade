# Home Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Home tells the day's story first: news moves and the brief merge into one `TodayCard` under the Hero, the rest restyled on the emerald identity, old-kit leftovers in Home's files and four shared files removed.

**Architecture:** One new component `components/home/TodayCard.jsx` absorbs `NewsMoves` + `BriefCard` (deleted); `pages/Home.jsx` reorders and restyles its inline bits; `GoalTile`/`WeeklyLink` and four shared files get class-only changes.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test` source/unit tests, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-home-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no backend change; no new npm dependency.
- Use existing primitives (`Card`, `ListRow`, `Tile`, `Badge`) and tokens; no `rounded-[16px]`, no `shadow-`, no `doc-meta`, no `border-dashed` in touched files.
- Text on an `--accent` fill uses `--accent-ink`. Money figures keep `private`.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- A day with news moves but no brief (in session) shows the card titled "Today" with only the moves block; no empty divider.
- Phase `pre` with no digest text and no AI summary, and no moves: card renders nothing (no empty Card shell).
- A move without `cause.url` is not tappable (no `onClick`), as today.
- Alert with `login` still calls `openBrokerLogin` and keeps `role="alert"` after the restyle.
- Hide-amounts: rupee column in TodayCard rows stays blurred (ListRow `privateValue` default not overridden).

---

### Task 1: TodayCard and Home order

**Files:**
- Create: `frontend/src/components/home/TodayCard.jsx`, `frontend/src/components/home/TodayCard.test.js`
- Delete: `frontend/src/components/home/NewsMoves.jsx`, `frontend/src/components/home/BriefCard.jsx`
- Modify: `frontend/src/pages/Home.jsx`, `frontend/src/pages/Home.test.js`, `frontend/src/handbook/ai-and-news.md:93`

**Interfaces:**
- Produces: `TodayCard({ moves, kind, text, summary })` default export. `moves` = news_moves array or undefined; `kind` = `briefKind(today.phase)` (`'premarket' | 'postclose' | null`); `text` = `today[kind]` (undefined when `kind` null); `summary` = `/summaries/day` summary or null.
- Also export a pure helper from the same file for tests: `todayTitle(kind)` -> `'Before the open' | 'After the close' | 'Today'`; and `briefLines(text, summary)` -> `{ ai: boolean, lines: string[] }` (AI lines from `summaryLines(summary?.text)` when non-empty, else `digestLines(text).slice(1)`; `[]` when `text` is falsy).

- [ ] **Step 1: Failing tests** in `TodayCard.test.js` (pure + source, same style as `pages/Home.test.js`):
  - `todayTitle('premarket') === 'Before the open'`, `todayTitle('postclose') === 'After the close'`, `todayTitle(null) === 'Today'`.
  - `briefLines(undefined, null)` deep-equals `{ ai: false, lines: [] }`; with a `summary.text` of three lines returns `ai: true` and those lines.
  - Source: returns `null` when no moves and no brief lines (`/return null/`); `noopener,noreferrer`; `onClick={m.cause?.url ?` (no handler without a url); `aria-expanded`; `Read all` and `Show less`; `/market` and `Your money` link labels; no `privateValue={false}`.
  - `Home.test.js` append: in `Home.jsx` source, index order `<HeroRow` < `alerts(today)` < `<SetupChecklist` < `<TodayCard` < `grid grid-cols-2` < `<GoalTile` < `<WeeklyLink`; no `NewsMoves` or `BriefCard` import; needs pill and alert links contain `tap`; pill uses `text-[var(--accent-ink)]`; alerts use `var(--loss-soft)` and no `border-[var(--loss)]`; alerts keep `role="alert"` and `openBrokerLogin`.
- [ ] **Step 2: Run** `cd frontend && node --test src/components/home/TodayCard.test.js src/pages/Home.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §2: `Card` with `title={todayTitle(kind)}` and `more` (premarket -> `{ to: '/market', label: 'Market' }`, else `{ to: '/money', label: 'Your money' }`); moves block = NewsMoves's `<ul>` of `ListRow dense` unchanged; brief block = BriefCard's body unchanged (AiLabel, AmountText, Read all toggle); `border-t border-[var(--border)] pt-3 mt-3` on the brief block only when moves showed. Home.jsx: new order per spec §1, pill `text-[var(--accent-ink)]` + `tap`, alert class `rounded-[12px] px-3 py-2 ... text-[var(--loss)] tap` with `style={{ background: 'var(--loss-soft)' }}`. Delete the two old files. Handbook line 93 names `components/home/TodayCard.jsx`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(home): Today card tells the day's story under the hero [skip ci]`.

### Task 2: Goal and Weekly on the identity

**Files:**
- Modify: `frontend/src/components/home/GoalTile.jsx:35-40`, `frontend/src/components/home/WeeklyLink.jsx`
- Test: `frontend/src/components/home/homeIdentity.test.js` (create)

- [ ] **Step 1: Failing source test**: neither file contains `rounded-[16px]`; both link elements carry `rounded-[20px]` and `tap`; GoalTile still links `/settings/goal` with "Set a goal" / "Home will track it"; WeeklyLink still uses `showWeekly()` and `/reports/weekly`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement**: swap `rounded-[16px]` -> `rounded-[20px]`, replace `active:bg-[var(--surface-2)]` with `tap`. Nothing else.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `style(home): goal and weekly links on the identity [skip ci]`.

### Task 3: Shared leftovers (classes only)

**Files:**
- Modify: `frontend/src/components/Layout.jsx:62,65`, `frontend/src/components/ChatWidget.jsx:291,322`, `frontend/src/components/common/NewsChip.jsx:12`, `frontend/src/components/common/StopAutopilot.jsx:29`
- Test: `frontend/src/components/common/leftovers.test.js` (create)

- [ ] **Step 1: Failing source test**: none of the four files contains `doc-meta`, `shadow-`, or ` sheet ` / `"sheet ` class; Layout toast has `rounded-[12px]` and `border-[var(--border)]`; ChatWidget launcher keeps `border border-[var(--border)]`; NewsChip and ChatWidget keep `truncate`.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement**: `doc-meta normal-case` -> `text-[13px] text-[var(--text-muted)]` (keep `block`/`truncate`/`max-w-*`); Layout toast `sheet ... shadow-lg` -> `rounded-[12px] border border-[var(--border)]`; ChatWidget launcher drop `shadow-[var(--sheet-shadow)]`.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `style(ui): drop doc-meta and shadows from shared chrome [skip ci]`.

### Task 4: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (row `src/components/home/*` line ~42, §4 Home line ~103, line ~164 `BriefCard` mention, `verified_at`)
- Scratch (not committed): `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/home-shots.mjs`, shots in `pw/home/`

- [ ] **Step 1: Wiki**: home row lists `TodayCard` (news moves + brief, title by phase, hidden when empty) in place of `BriefCard`/`NewsMoves`; §4 order matches spec §1; line ~164 says `TodayCard` `more`; bump `verified_at` to the base commit.
- [ ] **Step 2: Render**: reuse `pw/identity-shots.mjs` mocks; 390x844, both themes; `/` four ways: session with moves, `pre` with digest, `post` with AI summary + moves, session with no moves (card absent). Assert `scrollWidth <= 390`. Read every PNG. Fix visual breaks in Task 1-3 files only, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(home): wiki for the Today card [skip ci]` (plus a separate `fix(home): ... [skip ci]` if Step 2 changed code).

## Waves

1. Tasks 1, 2, 3 in parallel worktrees (disjoint files).
2. Task 4, final review, push (Direct).
