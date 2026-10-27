# Drill-down navigation

Date: 2026-10-27. Status: approved in chat, awaiting spec review.

## Problem

Most cards in the app are dead ends. `ui/Card` has no `to` prop (only `Tile` and `ListRow` link), and only
two detail pages exist (`/stock/:symbol`, `/ideas/:id`). A strategy, a trade, a journal round trip, a sector,
an index or a news item has nowhere to open. Worst pages by cards against links: Pulse (10/1),
Stock AnalysisTab (6/0), TaxTab (6/0), JournalTab (6/1), WeeklyReport (5/2), Stock (3/0).

## Goal

If a figure names a thing, tapping it opens that thing. Detail lives on its own page under the tab it belongs
to, with a back control and a shareable URL. Stats with nothing behind them stay plain.

Owner choices (2026-10-27): drill-down pages (not sheets or accordions); first pass covers AI, Money,
Market and a sweep of every remaining card.

## Navigation model

| Path | Page | Parent |
|---|---|---|
| `/ai/strategy/:name` | `AiStrategy` | `/ai?tab=scoreboard` |
| `/ai/trade/:id` | `AiTrade` | the strategy page, else `/ai?tab=positions` |
| `/money/trade/:id` | `RoundTrip` | `/money?tab=journal` |
| `/market/index/:ticker` | `IndexPage` | `/market?tab=pulse` |
| `/market/sector/:name` | `SectorPage` | `/market?tab=pulse` |
| `/news/:id` | `NewsItem` | `/market?tab=news` |

- Paths go in `utils/routes.js` with builders (`strategyPath`, `aiTradePath`, `roundTripPath`, `indexPath`,
  `sectorPath`, `newsPath`), each encoding its segment. `tabs.js::tabActive` already keeps the tab lit on sub-paths;
  `/news/:id` is added to Market's match.
- All six routes are `gated(...)`. None is admin-only, but admin-only fields stay admin-only (Picks grade on a
  `picks:*` strategy page follows the existing Picks admin rule).

## Building blocks

- **`Card to`**: with `to`, a card whose body has no links becomes one `Link` (chevron in the title row, the
  `Tile` hover/active/focus classes). A card that holds links (lists of rows) takes `more={{ to, label }}`
  instead: a "See all ›" link in the title row. Nested anchors are invalid HTML, so `to` and inner links
  never mix; the Card docstring states the rule.
- **`PageHeader backLabel`**: `back` stays as is (path or `true`). New `backLabel` prints the parent's name next
  to the chevron ("AI", "picks:pullback"). Detail pages pass `back` as the parent path, so a page opened from a
  shared link still has somewhere to go.
- **Rows**: every `ListRow` that names a strategy, trade, sector, index or news item gets `to` and shows its
  chevron.

## Pages

### AI

`/ai/strategy/:name`
- Stats: net closed, open (unrealized), vs NIFTY, win rate, trades: from `GET /analytics/scorecard?venue=paper`
  (the row for `name`).
- Status: proven / unproven (`useForward` badge), parked (new `parked` flag on each scorecard strategy row, from `fence.PARKED`),
  paused (`/today` `autopilot.paused`); a `picks:*` strategy shows its setup's grade and t for admins.
- Backtest card: `GET /trading/backtests/{name}` (exists; 404 = "No backtest recorded" empty state).
- Trades list: `GET /trading/trades?strategy=<name>&venue=paper`, newest first, each row to `/ai/trade/:id`.

`/ai/trade/:id`
- Entry and exit (time, price), quantity, gross P&L, costs, net; exit reason.
- Levels from `context`: stop, target, max hold, trail; for a pick, entry_ref and horizon.
- Why: `context.reason_codes` and `context.score` (rule / AI / final).
- Chart: the Stock page's daily chart component with entry and exit markers; link to `/stock/:symbol`.

Links in: Scoreboard strategy rows (drop `chevron={false}`), Positions rows (to the trade page; the row's
symbol is still reachable from the trade page), Activity rows keep `/stock/:symbol` (`autopilot_log` has no
trade id).

### Money

`/money/trade/:id` (journal round trip)
- Fills (time, side, qty, price), average entry and exit, hold time, P&L, charges, net.
- Note and tags editor (moved from the inline row; `PUT /journal/round-trips/{id}/note` unchanged).
- News at entry and exit (`NewsChips`, existing), and any `insights[]` that name this round trip.
- Link to `/stock/:symbol`.

Links in: Journal round-trip rows; Tax harvest rows and Overview top movers to `/stock/:symbol`.

### Market

- `/market/index/:ticker`: chart from `GET /market/index/{ticker}`, "why it moved" from
  `.../analysis` (both exist, unused today).
- `/market/sector/:name`: members sorted by today's move, the sector's news mood, its recent stories.
- `/news/:id`: title, source, published time, impacts (target, type, direction, impact /10), outcomes
  (1h / 1d / 5d move and vs bench) once scored, link to the article.

Links in: Pulse Indices rows, Sectors today rows, Sector news mood rows, Top movers (already link to stocks);
News tab rows and stock `NewsChips` to `/news/:id`.

### Sweep

Every remaining `Card` gets `to` or `more` where a natural target exists: Home brief and tiles, WeeklyReport
sections (AI to `/ai`, journal to `/money?tab=journal`, movers to stocks), Stock AnalysisTab cards (to the
relevant Stock tab or news item), TaxTab cards (to the holding). Cards with no target stay plain.

## Backend

All under existing routers, behind `get_current_user`, user-scoped by `user.id`.

| Endpoint | Change | Errors |
|---|---|---|
| `GET /analytics/scorecard` | each strategy row adds `parked: bool` (`autopilot/fence.py::PARKED`) | none new |
| `GET /trading/trades` | add `strategy: Optional[str]` filter (ledger query) | none new |
| `GET /trading/trades/{id}` | new: one round trip from the user's ledger | 404 not found or other user's |
| `GET /journal/round-trips/{id}` | new: `build_round_trips` over the user's trades, filtered by id, plus its note, news and insights | 404 |
| `GET /market/sector/{name}` | new: cached scan rows where `sector == name`, sentiment, recent sector news | 404 unknown sector |
| `GET /news/item/{id}` | new: `news_items` doc (public fields) + its `news_outcomes` rows | 404 |

No new collections or indexes. `paper_trades` has no index (wiki Gotcha); the per-id read filters on
`(user_id, id)`, fine at current volume. `ponytail:` note on the query, add an index if trades grow past ~50k.

## Error handling

Each new page follows DESIGN.md: Skeleton while loading, `ErrorLine` with Retry, an `Empty` that names what
fills it; a 404 shows "Not found" with a link to the parent. One failing section never blanks a page.

## Testing

- pytest per endpoint: happy path, 404, another user's id returns 404, `strategy` filter.
- vitest: route builders encode segments (`picks:pullback`, `^NSEI`, sector names with spaces); `Card` with
  `to` renders one link and a chevron; with `more` renders the title link only.
- `npm run build` (vitest is not a type/build check). Backend tests run in the prod image with `pytest.ini`.

## Delivery

Five commits, each deployed (deploy mode asked once per session):
1. Building blocks: `Card to/more`, `PageHeader backLabel`, route builders.
2. AI pages + `/trading/trades` filter and by-id read.
3. Money round-trip page + endpoint; Tax and Overview links.
4. Market index, sector, news pages + endpoints; Pulse and News links.
5. Sweep.

Wiki pages `frontend`, `platform`, and the handbook routes section update with each commit.

## Out of scope

Bottom sheets, breadcrumbs beyond one back label, a desktop split view, new data or analytics.
