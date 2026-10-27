# Market tab redesign

Date: 2026-10-27. Status: approved in chat, awaiting spec review.

## Problem

`/market` Pulse is one scroll of nine cards (`components/market/Pulse.jsx`): Indices, Breadth, Top movers,
Sectors today, Near 52-week highs/lows, Market today (AI), Regime and events, Sector news mood. The AI story of
the day sits below six cards of numbers; sectors appear twice (price heat map with a news dot, and a separate
"Sector news mood" card); nothing ties a move to its news.

## Goal

On a phone glance during the session, Market answers "what is the market doing, and why" first, then lets the
reader drill into breadth, movers and sectors. Owner choices (2026-10-27): story first with numbers as support;
sub-tabs Today / Sectors / News / Watchlist; no visual companion.

Reader and scene: the operator (PRODUCT.md), mostly on a phone in short glances 09:15-15:30 IST. Phone is the
design target, desktop second.

## Non-goals

- No new AI calls or prompts. The brief stays the stored `GET /market/brief`.
- No change to the index, sector, news item and stock detail pages (they stay the drill-down targets).
- No portfolio framing on Market ("your names" stays the News "My names" toggle).

## Navigation

`pages/Market.jsx` tabs: `today` (default) | `sectors` | `news` | `watchlist`. `?tab=pulse` maps to `today`
(the `useTabParam` alias argument from the stock page work). Every existing link into `/market?tab=news` or
`/market?tab=pulse` keeps working.

## Tab: Today (`components/market/Today.jsx`, replaces `Pulse.jsx`)

Top to bottom, each section loads and fails on its own (`useSection` pattern from Pulse):

1. **Story** — `GET /market/brief`: regime chip (Risk-on / Neutral / Risk-off from `regime.label`) and the first
   two lines of the brief (`AiMarkdown` clamped to 2 lines), "Read more" expands the full brief. "as of" from
   `as_of`; outside the session the label reads "Last session". 404 = "No brief yet".
2. **Indices** — `GET /market/indices`: NIFTY 50, BANK NIFTY, SENSEX as three tiles (level, % change, a sparkline of
   the latest session from the new `GET /market/index/{ticker}/intraday`); tap opens `indexPath(symbol)`. The other
   indices (VIX, globals) as compact rows under a "More indices" disclosure. "as of" kept (`AsOf`).
3. **Breadth** — `GET /market/scan` `breadth`: the existing bar plus a one-word read: "Broad rally" (up share
   >= 0.7), "Leaning up" (>= 0.55), "Mixed" (> 0.45), "Leaning down" (> 0.3), "Broad sell-off" (<= 0.3).
4. **Movers** — `scan.gainers` / `scan.losers`, 5 each: on phones a two-option segmented toggle (Gainers | Losers),
   on `sm+` two columns. Each row: symbol, % change, last price, and a news dot when `news` is true (see Backend);
   tap opens the stock page.
5. **Events today** — `GET /today` `backdrop.events` (the old Regime card's list, up to 5); hidden when empty.

## Tab: Sectors (`components/market/Sectors.jsx`)

- **One heat map** from `scan.sectors` (price move = cell colour via `ui/chartTheme::heatColor`, as now; "N of M up";
  news mood dot from `sentiment`; the existing `utils/market.js::divergence` flag when news and price disagree).
  It replaces both "Sectors today" and "Sector news mood" (the `newsFeed` SECTOR read on Pulse is dropped).
- **Sort** segmented control: Move | News | Breadth (`up/n`), default Move (largest absolute move first).
- Tap a cell opens `sectorPath(sector)`.
- **Extremes** below: the existing "Near 52-week highs and lows" content (`scan.near_high` / `near_low`).

## Tab: News (`components/market/News.jsx`, restyled)

- Scope chips and "My names" (default on) unchanged; socket refresh unchanged.
- Row: a 3 px left bar in gain / loss / muted by the strongest impact's direction; impact as "High" (>= 7),
  "Med" (>= 4), "Low" instead of "n/10"; scope · source · time ago. Title links to `newsPath(id)` as now.
- **Material today**: material items published since the IST day start are pinned in their own group at the top.

## Tab: Watchlist (`components/market/Watchlist.jsx`, restyled)

- Rows in the movers' row style: symbol, price, day %, news dot; remove stays behind the existing control.
- Empty state: "Track a stock" with an action that focuses the masthead stock search.

## Backend

- `routers/market_data.py`: `GET /market/index/{ticker}/intraday` — 5-minute closes of the latest session for a
  tracked index (`_known_index_names`, 404 otherwise) via yfinance on the ticker as-is (same path as
  `_fetch_index_detail_sync`), `[{t, close}]`, cached in-process 60 s per ticker; 502 when empty.
- `/market/scan`: each gainer/loser row gains `news: bool` — a SCORED `news_items` doc with a `symbol` impact on that
  stock published in the last 24 h (one query over the movers' symbols, using the `impacts.target`+`published_at`
  index). Failure leaves `news` false. Fixes the review note: `get_market_scan` stops returning `movers` (the full
  list) to clients; the cache keeps it for the sector page.

## Visual direction

DESIGN.md tokens only (`frontend/src/index.css`); tabular figures; gain/loss colour only for direction; sections
inside fewer surfaces (a tab is one or two Cards with internal section headers, not one Card per fact); 44 px touch
targets; skeletons shaped like the final content. Each tab gets an impeccable design pass (polish + audit) during
the build. Sparklines and charts use `ui/chartTheme` (recharts), per DESIGN.md.

## States

- Market closed: "Last session" instead of "today" in every heading and the story label.
- Stale: existing `AsOf` turns warn-coloured past its threshold.
- Each section: its own Skeleton, ErrorLine with Retry, and Empty with an action.

## Testing

Backend (pytest): intraday route (tracked ticker returns points; unknown 404; empty 502); scan movers carry `news`
(true with a scored symbol impact in 24 h, false without, false when the news query fails); scan response has no
`movers` key.

Frontend (node:test): `breadthWord(b)` thresholds; `impactWord(n)` thresholds; `sortSectors(rows, by)`;
`materialToday(items, now)`; `?tab=pulse` -> `today`; source checks that Today renders Story before Indices.
Then `npm run lint`, `npm test`, `npm run build`, full pytest.

## Docs

`docs/wiki/frontend.md` (Market flow), `docs/wiki/platform.md` and `docs/wiki/data-ai-jobs.md` (both cover
`routers/market_data.py`: new route, scan `news`, no `movers`), `frontend/src/handbook/jobs-and-ops.md` where it
names the Market page; wiki pages get `verified_at`.
