# Daily workstation (Phase 21 step 2): design

Date: 2026-10-19. Status: approved in chat, awaiting spec review.
Source plan: "NeoTrade redesign: Picks you can trust" (Claude Docs, `App structure` section) and
`docs/ROADMAP.md` Phase 21 step 2.

## Goal

The owner runs a trading day from one coherent app: what to do before the open, during the
session and after the close. The tab layout follows the plan doc's App structure table, with one
change chosen 2026-10-19: Lab is a tab for admins, not a header link.

## Decisions

- Today stays one page. Its sections reorder by market phase (pre / session / post / closed).
  No mode switcher.
- Tabs follow the plan doc. Lab is a 6th tab, admin only. Settings and search sit in the header.
- No new data sources. Every Today section is an existing component or an existing digest text.
- Two waves: A = IA move, B = phase-aware Today. B needs `backend/core/market_calendar.py`
  (Phase 21 step 1, wave 2) on main first.

## Wave A: navigation and routes

### Tabs (`frontend/src/components/layout/sections.js`)

| Tab | Path | Who | Sub-tabs |
|---|---|---|---|
| Today | `/` | all | none |
| Picks | `/picks` | admin | as today |
| AI | `/ai` | all | Overview · Book · Activity |
| Portfolio | `/portfolio` | all | Overview · Holdings · Tax · News · Watchlist · Import |
| Journal | `/journal` | all | Trades · Habits · Guardrails |
| Lab | `/lab` | admin | Strategies · Autopilot limits · Options · Handbook · Backlog |

- `SECTIONS` gains an `admin` flag; the bottom bar and desktop index drop admin tabs for others.
- The phone bar's grid uses the visible tab count (6 for admin, 4 otherwise) instead of `grid-cols-5`.
- Badges: Today keeps `attention`; the `pending` (Needs you) badge moves from Mine to Portfolio.
- `MINE_TABS`, `RESEARCH_TABS` are replaced by `PORTFOLIO_TABS`, `JOURNAL_TABS`, `LAB_TABS`;
  `AI_TABS` loses Strategies and Settings.

### Header

- Search box: symbol lookup that navigates to `/stock/:symbol` (reuses the search used by
  `/research` today).
- Settings icon to `/settings` (Accounts · Alerts · Plan · Profile; `/profile` stays a route).

### Routes (`frontend/src/App.jsx`)

| New path | Page | Old path(s), now redirects |
|---|---|---|
| `/portfolio` | MineOverview | `/mine` |
| `/portfolio/holdings` | MineHoldings | `/mine/holdings` |
| `/portfolio/tax` | MineTax | `/mine/tax` |
| `/portfolio/news` | News | `/research/news` |
| `/portfolio/watchlist` | Watchlist | `/research/watchlist`, `/watchlist` |
| `/portfolio/import` | Import | `/import` |
| `/journal` | Journal (`lockedAccount="mine"`) | `/mine/journal`, `/mine/trades` |
| `/journal/habits` | Journal habits tab | `/mine/habits`, `?tab=patterns|learning` |
| `/journal/guardrails` | guardrail block moved out of Settings | Settings safety section |
| `/picks` | Picks (RequireAdmin) | `/research/picks` |
| `/lab` | Strategies (RequireAdmin) | `/ai/strategies` |
| `/lab/limits` | AiLimits (RequireAdmin) | `/ai/settings` |
| `/lab/options` | OptionChain (RequireAdmin) | `/research/options`, `/options` |
| `/lab/handbook` | Handbook (RequireAdmin) | `/system` |
| `/lab/backlog` | Backlog (RequireAdmin) | `/system/future` |
| `/stock/:symbol` | merged stock page | `/mine/stock/:symbol`, `/research/stock/:symbol` |
| (none) | redirect to `/` | `/research`, `/scanner`, `/research/scanner`, `/mine/ideas` |

- Every redirect in the existing `Moved` list is retargeted to its final path in one hop
  (no chains). `/portfolio` and `/journal` stop being redirects and become real routes;
  `JournalMoved`'s query handling moves onto `/journal`.
- Backend links that point at app paths (Telegram texts, digest links, `needs_you` items, handbook
  pages) are updated to the new paths; grep for `/mine`, `/research`, `/ai/settings`,
  `/ai/strategies`, `/system` in `backend/` and `frontend/src/handbook/`.
- Options moving to Lab makes it admin only. That matches the plan doc ("Everything frozen behind
  the Lab switch").

### Stock page

- `/stock/:symbol` = MineStock as the base (position, lots, chart with trades, thesis, events,
  news), then Dashboard's analysis section below it. Not held = the position block is omitted.
- Chat on a stock page starts with that symbol as context (already done by the chat widget's
  route context, retargeted to the new path).

## Wave B: phase-aware Today

### Backend (`backend/routers/today.py`)

`/today` adds:

- `phase`: `pre` (trading day, 00:00 to 09:15 IST), `session` (09:15 to 15:30), `post`
  (15:30 to 24:00), `closed` (weekend or NSE holiday, from `market_calendar`).
- `next_open`: ISO time of the next 09:15 IST on a trading day.
- `premarket` (phase `pre` only): the text from `digest.premarket_text`, same inputs as the 08:45
  Telegram.
- `postclose` (phase `post` only): the text from `digest.postclose_text`.
- `unjournaled`: count of the user's closed `mine` trades today with no journal note.
- `picks_top` (admin only, phase `pre`): the top 3 of today's picks (same source as
  `/picks/today`).

Each new field fails soft into `errors.<field>` like `pulse` and `scoreboard` do.

### Frontend (`frontend/src/pages/Today.jsx`)

A per-phase ordered list of sections; absent data hides a section.

| Phase | Order |
|---|---|
| pre | StatusStrip, Before the open, Picks top 3, Do today, Your account, Markets |
| session | StatusStrip, Do today, Your account, AI activity, Markets |
| post | StatusStrip, After the close, Journal prompt ("N trades to journal" to `/journal`), You vs Picks, Your account, AI activity |
| closed | StatusStrip, "Market closed, opens <next_open>", After the close (last session), You vs Picks, Your account |

SetupChecklist stays above all phases while setup is incomplete. The page re-reads `phase` on its
60 s poll, so it moves at 09:15 and 15:30 without a reload.

## Error handling

- Unknown or missing `phase` (old backend during a rolling deploy) = the `session` order, which
  is today's layout.
- Redirects keep query strings (the `Moved` component already does).

## Testing

- vitest: `SECTIONS` visibility per role and the bar's column count; phase-to-order mapping; the
  redirect table resolves every old path to a real route in one hop.
- pytest: `phase` at 09:14/09:15, 15:29/15:30, a Saturday, an NSE holiday; `unjournaled` count;
  `picks_top` absent for non-admins.
- Gate: `npm run build` and vitest; pytest inside the prod image; manual phone-width check of the
  6-tab bar.

## Docs to update

`PRODUCT.md` Surfaces, `docs/wiki` (frontend page map), handbook pages that name paths,
`docs/ROADMAP.md` Phase 21 step 2 status.

## Out of scope

New Today data, notification changes, Research Lab (step 3), any billing or public-user work.
