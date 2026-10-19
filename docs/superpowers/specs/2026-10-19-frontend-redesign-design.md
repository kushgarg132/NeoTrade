# Frontend redesign: a clear user journey (design)

Date: 2026-10-19. Status: approved screen by screen in the visual companion, awaiting spec review.
Replaces the navigation from `2026-10-19-daily-workstation-design.md` (its backend `/today` phase
work stays).

## Why

The owner finds the app unusable: it is unclear what to do, details he wants are missing or
buried, some pages hold too much and others are hard to read. He opens the app for four jobs:
check my money, decide what to buy/sell, watch the AI account, research a stock. The details he
wants in minimum taps: portfolio numbers, why something moved, idea details, AI results.

## Decisions (owner, 2026-10-19)

| Question | Choice |
|---|---|
| Home shape | Hub of 4 tiles (My money · Ideas · AI · Market), each with its headline number |
| My money | Header + tabs: Overview · Holdings · Tax (+ Journal, from the app map) |
| Ideas | List, then a detail page per idea |
| AI account | Header with Stop AI + tabs: Scoreboard · Positions · Activity |
| Stock page | Header (price, verdict, your position) + tabs: Chart · News · Analysis · Events |
| App map | 5 bottom tabs = Home · Money · Ideas · AI · Market; header = search, profile/settings; Lab inside Settings (admin) |
| New features | Daily brief on Home, goal tracker, weekly report |
| Style | Clean modern (light + dark), drops the "Contract Note" paper look |

Mockups: `.superpowers/brainstorm/554992-1792414279/content/` (journey-shape, money-screen,
ideas-screen, ai-screen, stock-screen, app-map).

## Approach

Rebuild inside the existing React 19 + Vite + Tailwind 4 app, not a new app: keep `utils/api.js`,
auth, the live socket (`useStream`), privacy mask, second-tap live-order flow, and the data
fetching already written per page; replace the shell, the design tokens and the page layouts.
Old routes redirect (one hop, query kept) to their new home.

## Design system

- Tokens in `frontend/src/index.css` (`:root` light, `[data-theme=dark]` dark), replacing the
  paper/ink/stamp palette: `--bg`, `--surface`, `--surface-2`, `--border`, `--text`,
  `--text-muted` (≥ 4.5:1 on its surface), `--accent` (blue), `--gain` (green), `--loss` (red),
  `--warn` (amber); radius 12/16 px; spacing 4-px scale; body 15 px, labels ≥ 12 px; numbers in
  tabular figures.
- Primitives in `frontend/src/components/ui/`: `Tile`, `Card`, `Stat` (label + value + delta),
  `Tabs` (segmented, URL-backed `?tab=`), `ListRow` (title, sub-line, right value, chevron),
  `Badge` (proven / unproven n/100 / paper / live), `Button` (primary, secondary, danger),
  `PageHeader` (back, title, right action), `Empty` (what it is + the one action to fill it),
  `Skeleton`.
- Phone first (390 px design width, 44 px touch targets); desktop: same pages in a centred
  max-width column with the bottom tabs as a left rail.

## Shell

- Header (every screen): 🔍 search (opens the stock page), 👤 profile/settings. Market-phase
  dot stays.
- Bottom tabs: Home `/`, Money `/money`, Ideas `/ideas`, AI `/ai`, Market `/market`.
  Badges: Ideas = exit alerts + new proven ideas; Home = setup/attention count.
- Chat (margin note) stays a floating button.

## Screens

### Home `/`

- Today's line: market phase + "N things need you" link (to Ideas) + setup checklist until done.
- Brief card (new): before 09:15 the morning brief, after 15:30 the evening brief, plain text
  (from `/today` `premarket` / `postclose`); collapsed to 3 lines, "Read all".
- 4 tiles (2×2), each one tap to its tab:
  - My money: value, today ₹ and %, XIRR (`/today` `pulse`, `/mine/overview`).
  - Ideas: count; "2 proven · 1 exit alert" (`/today` `needs_you`, `/suggestions`, `/picks`).
  - AI: today % and month vs you (`/today` `scoreboard`, AI book).
  - Market: NIFTY today %, regime (`/today` `backdrop`).
- Goal tile (new, when a goal is set): progress bar and pace (see New features).
- Weekly report link on Sundays/Mondays (new).

### Money `/money` — header: value, today ₹/%, XIRR vs NIFTY; tabs

- Overview: value vs NIFTY chart (1M/6M/1Y/All, `/mine/history`), invested, total P&L, today's
  top 3 movers with "why" (one line from news/results; "moved with the market" fallback).
- Holdings: every holding — today %, value, weight %, total P&L %, one-line why, verdict badge;
  sort by today/value/P&L; tap → stock page. Import link at the bottom.
- Tax: this FY's gains (STCG/LTCG), harvesting hints (`/mine/tax`).
- Journal: trades net of charges, habits, guardrails (current Journal content, restyled).

### Ideas `/ideas` (list) and `/ideas/:id` (detail)

- List sections: Exit alerts on your holdings (stop/target/verdict, from `/mine/actions`), then
  New ideas (proven-strategy suggestions for Mine + today's Picks for admins), each row: action,
  symbol, setup, horizon, median expected %, proven/unproven badge.
- Detail: why (rule codes in words), Entry/Stop/Target, size (qty, ₹, risk ₹), expected range bar
  (p10/median/p90), chance up, beat-NIFTY rate, setup track record (past n, OOS excess, forward
  record n/100 from `/forward/scorecard`), Buy (existing second-tap flow) / Skip; exit alerts get
  Sell / Later / Dismiss.
- History `/ideas/history`: past ideas and picks with outcome (Picks history + forward records).

### AI `/ai` — header: value, today %, paper/live badge, **Stop AI** (kill switch, confirm); tabs

- Scoreboard: this month AI vs you vs NIFTY, win rate, trades, charges, max drawdown;
  strategies with proven status.
- Positions: the AI book (current `/ai/book` content).
- Activity: every order/skip with its reason (current AI activity).

### Market `/market` — tabs

- Pulse: NIFTY + sector moves, breadth, regime, today's events (current Markets backdrop,
  `/market/indices`).
- Watchlist: current Watchlist restyled.
- News: holdings first, then market (current News).

### Stock `/stock/:symbol`

Header: price, today's move, verdict badge, your position (qty, avg, P&L, weight); tabs Chart
(1D/1M/1Y/5Y with your buys/sells marked) · News · Analysis (current Dashboard analysis) ·
Events; bottom bar Buy / Sell (existing ticket + second tap).

### Settings `/settings` (from the profile icon)

Accounts (brokers), Alerts (Telegram), Limits (guardrails + autopilot limits), Profile, Theme,
Goal; **Lab** (admin): Strategies, Options, Runs, Forward, Handbook, Backlog.

## New features

1. **Daily brief on Home** — frontend only; reuses `/today` `premarket`/`postclose`.
2. **Goal tracker** — one goal per user in prefs: `{kind: "value" | "beat_nifty", target: number,
   by: "YYYY-MM-DD"}` (`PUT /settings/preferences`, validated: target > 0, by in the future).
   Progress from `/mine/overview` (value) or `/mine/history` (your return − NIFTY return since
   the goal's start date, stored as `goal.start` when set). Pace = required monthly growth vs
   actual trailing 3-month growth. Home tile + Settings › Goal.
3. **Weekly report** — backend `GET /reports/weekly?week=YYYY-Www` (default last completed
   week): your return vs NIFTY, AI vs you, best/worst 3 holdings, ideas taken vs skipped and how
   both did (forward records), journal summary (trades, net P&L, charges). Page `/reports/weekly`;
   Telegram summary Sunday 18:00 IST from the jobs scheduler (once per user per week, Redis
   guard), same text builder as the page.

## Redirects

Every current route redirects in one hop to its new home (query kept), e.g. `/portfolio` →
`/money`, `/portfolio/holdings` → `/money?tab=holdings`, `/portfolio/tax` → `/money?tab=tax`,
`/journal` → `/money?tab=journal` (its `?tab=habits|guardrails` mapped), `/picks` → `/ideas`,
`/ai/book` → `/ai?tab=positions`, `/ai/activity` → `/ai?tab=activity`, `/portfolio/news` →
`/market?tab=news`, `/portfolio/watchlist` → `/market?tab=watchlist`, `/lab*` →
`/settings/lab*`. The existing `utils/routes.js` table and its one-hop test are extended.

## Error and empty states

Every tile and tab shows a skeleton while loading, a one-line error with Retry on failure (never
a blank card), and an `Empty` with the action that fills it (connect broker, import, set goal).
A failed section never blanks the rest of the page.

## Testing

- node:test: route/redirect table (one hop, admin routes), goal progress/pace maths, tile
  headline formatters, idea detail formatter (levels, range, badges), weekly-report text helpers
  if any live in the frontend.
- pytest: `/reports/weekly` numbers on fixtures (vs NIFTY, AI vs you, ideas taken/skipped),
  Sunday send once per week, goal prefs validation.
- `npm run build`; Playwright screenshots at 390 px and 1280 px for Home, Money, Ideas list and
  detail, AI, Market, Stock, Settings in light and dark, checked by eye before deploy.

## Out of scope

Price/news alerts (not chosen), new data sources, changes to trading logic or gates, native app.

## Delivery

Phased so each phase ships usable: (1) design system + shell + Home; (2) Money; (3) Ideas +
stock page; (4) AI + Market + Settings/Lab + redirects; (5) goal tracker + weekly report. The
plan sets the waves.
