# Page-by-page redesign (design)

Date: 2026-10-23. Status: design approved in chat, awaiting spec review.
Builds on `2026-10-19-frontend-redesign-design.md`: the shell, the five tabs, the tokens and the
`components/ui/` primitives stay. This pass reworks each page's content, not the navigation.

## Goal

Every page reads well for two people:

- **An experienced Indian equities trader**: scans fast, wants dense data, P&L and risk on screen
  without a tap, and the fewest clicks to act.
- **A new user**: knows what the page is for, sees an empty state that says what fills it, reads
  plain words instead of jargon.

## Constraints

- Honest account labels (owner, 2026-10-23): figures from **Mine** are the trader's own broker
  account and are labelled as such. Every AI, Picks and strategy figure carries the **Paper** label
  until it is live. No advice wording ("you should buy"); verdicts stay the engine's, worded as
  the engine's.
- Picks stay admin-only (no change to the existing gate).
- No new libraries. Charts use the installed `recharts`; icons use `lucide-react`.
- No backend or API changes: pages show only data that the endpoints already return.
- Shared folders are read-only to page work: `components/ui/`, `components/common/`,
  `components/doc/`, `components/layout/`, `src/index.css`. A page that needs a shared change
  reports it, and the change lands between waves.
- Gate per page: `npm run build && npm test` (`node --test`; this repo has no vitest).

## Wave 0: foundation (one branch, `redesign/pages`)

1. **Critique** (impeccable, critique mode) of the current UI across all pages. Output: a
   cross-page findings list, given to every lane.
2. **Chart tokens** (dataviz): `--chart-1` … `--chart-6` categorical, a sequential ramp and a
   diverging gain/loss ramp for heatmaps, light and dark, passing the dataviz validator. Added to
   `src/index.css` and documented in `DESIGN.md`.
3. **`components/ui/chartTheme.js`**: the recharts axis, grid and tooltip props, read from the tokens,
   used by every chart, gauge and heatmap.
4. **`ListRow` `dense` prop**: a 36 px row for trader-density lists; the default stays 44 px.
5. **Screenshot harness** (not committed, `.superpowers/sdd/2026-10-23-page-redesign/`): a
   Playwright script that serves the build, mocks `/api/v1/**` from fixture JSON per page, sets
   `localStorage.neotrade_token`, and shoots each route at 390×844 and 1280×800, light and dark,
   full and empty fixtures.

## Waves 1–2: page lanes

A lane is one Sonnet subagent in its own git worktree, owning pages that share a component folder,
committing one page at a time. Lanes in a wave run in parallel and merge into `redesign/pages` in
order.

| Wave | Lane | Pages, in order | Owned folders |
|---|---|---|---|
| 1 | A | Home | `components/home/` |
| 1 | B | Market | `components/market/` |
| 1 | C | Stock | `components/stock/`, `components/trading/` |
| 1 | D | Money | `components/money/`, `components/mine/` |
| 1 | E | Ideas, IdeaDetail, IdeasHistory | `components/ideas/` |
| 1 | F | Login | (page only) |
| 2 | G | Ai, WeeklyReport | `components/ai/` |
| 2 | H | Strategies, OptionChain | `components/strategies/`, `components/dashboard/`, `components/paper/`, `components/journal/` |
| 2 | I | LabRuns, LabForward | (pages only) |
| 2 | J | Handbook, Backlog | `components/system/` |
| 2 | K | SettingsHome, Profile | `components/settings/` |

Lab pages (H, I, J) are frozen admin features: clarity and density fixes only, no restructuring.

### Per-page loop

1. Critique the page as the trader and as the new user.
2. List the top 5 fixes, ranked by impact; implement them.
3. Check 390 px width and dark mode.
4. `npm run build && npm test`.
5. Screenshots with the harness (example-skills:webapp-testing).
6. One commit: `feat(ui/<page>): <what changed>`, the five fixes listed in the body.

Each lane reports, per page: the five fixes, any shared-folder change it needs, and the
screenshot paths.

### Agent rules

- STRICT no push. After each wave, `origin/main` is checked against its pre-wave SHA.
- Edit only the lane's pages and owned folders. No edits to `docs/`.
- Keep every existing behaviour: data fetching, the live socket, the privacy mask (`private`
  class on the user's money), the second-tap order flow, `?tab=` URLs.

## End

1. Merge the lanes, apply queued shared-folder changes, rebuild and retest.
   Update `docs/wiki/frontend.md` (sections and `verified_at`) once here, not per lane, so parallel
   lanes never conflict on it.
2. impeccable-finish-reviewer over the whole branch; fix what it finds.
3. Ask the deploy mode, then merge `redesign/pages` into `main` and push.

## Out of scope

New features, new endpoints, navigation changes, the backend.
