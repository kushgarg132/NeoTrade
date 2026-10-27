# Ideas + AI redesign: AI book on the Hero, ideas grouped by grade

Date: 2026-10-27. Status: approved in chat. Sub-project 4 of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`; pattern as Money: `2026-10-27-money-redesign-design.md`).
Frontend only, no backend change.

## Intent

- Owner: AI header on the Hero; Ideas list restructured into grade groups; leftovers go.
- Owner rule: every feature, control, link and piece of data stays; simplest result.

## 1. AI (`frontend/src/pages/Ai.jsx`)

- The `rounded-[16px]` header div becomes, once loaded,
  `<Hero label="AI book" value={value} change={<DeltaChip value={day} pct={typeof dayPct === 'number' ? dayPct * 100 : undefined} suffix="today" />}>`
  (`aiBook` gives `dayPct` as a fraction; DeltaChip wants percent units). No `to`.
- Children, in order, same logic as today: Paper/Live + Autopilot badges row; cap-deployed line (or its
  `ErrorLine`); Lab-off line; paused line; `StopAi` when on, else the "Turn the autopilot on in Settings" link.
- While `!today.loaded || !pnl.loaded`: `<Card><Skeleton rows={2} /></Card>`.
- Tabs and tab bodies unchanged.

## 2. Ideas, Picks tab (`frontend/src/pages/Ideas.jsx`, `frontend/src/utils/ideas.js`)

- `groupByGrade(items)` replaces `splitByEvidence` (remove it and its test; add tests for the new one):
  returns `{ engine, A, B, C }` arrays, preserving input order: `engine` = `kind !== 'p'`; `A`/`B` = picks
  with that grade; `C` = picks with grade `C` or no/unknown grade.
- Inside the existing "New ideas" `Card` (intro line, Paper badge unchanged), in order, each only when
  non-empty, under a header `<h3 className="mt-3 mb-1 text-[13px] font-semibold text-[var(--text-muted)]">`:
  "Engine ideas", "A · Proven", "B · Promising" (labels from `GRADES`). Then C behind the existing toggle
  button (same copy, `aria-expanded`, rows at `opacity-80`).
- The "No proven setup has fired right now…" line shows when `engine`, `A`, `B` are all empty and `C` is not.
- Empty state, loading, error, History link, Holdings tab unchanged.

## 3. IdeaRow (`frontend/src/components/ideas/IdeaRow.jsx`)

- A pick with `GRADES[idea.grade]` shows `<GradeTile grade={idea.grade} />` as the first child of the row
  link (left of the symbol block); the grade `Badge` is removed. Non-picks: no tile, no placeholder.
- News pills `NEWS` map: `--gain-wash` -> `--gain-soft`, `--loss-wash` -> `--loss-soft`.
- `IdeaDetail.jsx` keeps its grade Badge (sub-project 6).

## 4. Leftovers

- `components/ai/{Scoreboard,Positions,Activity}.jsx` settings links: `text-[var(--surface)]` on
  `bg-[var(--accent)]` -> `text-[var(--accent-ink)]`.
- `components/suggestions/SuggestionRecord.jsx` alert (~line 253): `-wash` -> `-soft`.
- `doc-meta` uses stay (decided in sub-project 3).
- `docs/wiki/frontend.md`: AI and Ideas sections, `verified_at`.

## 5. Tests and checks

- `utils/ideas.test.js`: `groupByGrade` splits engine/A/B/C in order; missing grade goes to C; empty input
  gives four empty arrays.
- Source tests: Ai.jsx imports Hero + DeltaChip, `label="AI book"`, `dayPct * 100`, no `rounded-[16px]`;
  Ideas.jsx uses `groupByGrade`, headers from `GRADES`, keeps the C toggle copy and `aria-expanded`;
  IdeaRow imports `GradeTile` and no grade `Badge`; no `-wash)` in IdeaRow/SuggestionRecord; no
  `bg-[var(--accent)]` + `text-[var(--surface)]` in components/ai/*.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: `/ai` (scoreboard, positions, activity; autopilot on and
  off); `/ideas` with engine+A+B+C, only C, empty; `/ideas?tab=holdings`. `scrollWidth <= 390`.
- Deploy Direct (`[skip ci]`), frontend only.

## Out of scope

IdeaDetail and other detail pages (sub-project 6), backend, the 53 `doc-meta` uses.
