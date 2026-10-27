# Home redesign: the day's story first

Date: 2026-10-27. Status: approved in chat. Sub-project 2 of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`). Frontend only, no backend change.

## Intent

- Owner: Home answers "what happened today" first, right under the Hero.
- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Assumed: phone (390 px) is the main screen; only order, look and copy change.

## 1. Layout (`frontend/src/pages/Home.jsx`, top to bottom)

1. Status strip: phase label left, "N need(s) you" pill right (same link and title as now);
   pill text `--accent-ink` on `--accent`, gets `tap`.
2. `HeroRow` (Hero + DeltaChip), unchanged.
3. Alert banners from `alerts(today)`: same links, same `openBrokerLogin` behaviour, `role="alert"`.
   Restyled: `rounded-[12px]`, `background: var(--loss-soft)`, no border, text `--loss`, action underlined.
4. `SetupChecklist`, same behaviour (Skip / Undo, `setup_skipped`).
5. `TodayCard` (new), see §2.
6. AI + Market `Tile`s in the 2-column grid, same data and meta.
7. `GoalTile`.
8. `WeeklyLink`.

## 2. TodayCard (`frontend/src/components/home/TodayCard.jsx`)

Replaces `NewsMoves.jsx` and `BriefCard.jsx` (both deleted; their logic moves here).

Props: `{ moves, kind, text, summary }`: `moves` = `(overview?.headline || today.pulse)?.news_moves`;
`kind` = `briefKind(today.phase)` (`'premarket' | 'postclose' | null`); `text` = `today[kind]`;
`summary` = `/summaries/day` summary.

- Title: `kind === 'premarket'` -> "Before the open"; `'postclose'` -> "After the close"; else "Today".
- Block 1, news moves (when `moves?.length`): same rows as NewsMoves today (symbol + move %,
  `newsWhy`, signed rupees with tone; tap opens `cause.url` in a new tab with `noopener,noreferrer`).
- Block 2, the brief (when `kind` and lines exist): exactly BriefCard's logic: AI lines
  (`summaryLines`) with `AiLabel` and `AmountText`, else `digestLines(text).slice(1)`, first 3 with
  "Read all" / "Show less" (`aria-expanded`).
- Blocks separated by a `--border` divider when both show.
- Neither block has content -> render nothing.
- `more` link: premarket -> `{ to: '/market', label: 'Market' }`; otherwise -> `{ to: '/money', label: 'Your money' }`.
- Money figures keep `private` (ListRow's default `privateValue` on the rupees column; `AmountText` as today).

## 3. Restyle and leftovers

- `GoalTile`: the "Set a goal" link is a `Card` with radius 20 and `tap` (no `rounded-[16px]`);
  goal card unchanged.
- `WeeklyLink`: same link and Sunday/Monday rule, radius 20, `tap`.
- Shared files, classes only:
  - `Layout.jsx` news toast: `sheet shadow-lg` -> `rounded-[12px] border border-[var(--border)] bg-[var(--surface)]`.
  - `doc-meta` -> `text-[13px] text-[var(--text-muted)]` in `NewsChip.jsx`, `StopAutopilot.jsx`,
    `Layout.jsx`, `ChatWidget.jsx` (keep `truncate` / `normal-case` behaviour where present).
  - `ChatWidget.jsx` launcher: `shadow-[var(--sheet-shadow)]` dropped (border stays).
- `handbook/ai-and-news.md`: references to NewsMoves/BriefCard point at TodayCard.
- `docs/wiki/frontend.md`: Home section lists TodayCard, `verified_at` bumped (wiki rule).

## 4. Tests and checks

- Source test `pages/Home.test.js` (extend): render order Hero -> alerts -> SetupChecklist ->
  TodayCard -> tiles -> GoalTile -> WeeklyLink; no import of NewsMoves/BriefCard.
- `components/home/TodayCard.test.js`: title per kind; hides when both blocks empty; each block
  alone; `noopener,noreferrer`; `private` on rupees.
- Source test: none of `doc-meta`, `shadow-`, `rounded-[16px]` in Home.jsx, components/home/*,
  NewsChip, StopAutopilot, Layout, ChatWidget.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: `/` in session, pre, post, and empty (no moves, no
  brief); `scrollWidth <= 390`; screenshots reviewed.
- Deploy Direct (`[skip ci]`), frontend only; Vercel builds on push.

## Out of scope

Other pages (sub-projects 3-7), backend, new data, charts.
