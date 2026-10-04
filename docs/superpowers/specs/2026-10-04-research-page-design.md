# Research: a URL per stock, a front page about stocks

Date: 2026-10-04 · Status: design approved in chat ("Yes"), awaiting spec review

Sub-project 4 of 4 (scanner → order ticket → decisions inbox → **research search page**).

## Problem

- A stock opens by pushing `state: { symbol }` into `/research`: no URL, Back leaves the page,
  refresh loses it, it cannot be shared.
- **Bug:** `Scrip` (`components/doc/Doc.jsx`), the stock-name link used across the app, links to
  `/` with `state` — Today ignores it, so tapping a stock name in holdings or ledgers opens
  nothing.
- The Research front page is mostly the user's broker statement (`BrokerPnl`, `PortfolioGlance`,
  guardrail alerts, live engine orders), not research.
- Search suggestions show symbol and name only.

## Goal

Every stock has its own page at `/research/stock/:symbol`; the Research front page is search,
recent stocks, the watchlist and markets; suggestions show the price.

## Non-goals

- Index pages stay state-based (`state: { index }`).
- No server-side search history (recent stocks are per device).
- No change to the stock page's content (`AnalysisCard`, from sub-projects 2's header buttons).

## Backend

`GET /market/quotes?symbols=ITC,INFY` (`backend/routers/market_data.py`):
- 1–8 bare NSE symbols, comma separated, upper-cased, de-duplicated; more than 8 or none → 422.
- One `yf.download([f"{s}.NS" ...], period="5d", interval="1d", group_by="ticker",
  progress=False, threads=True)` in `asyncio.to_thread`, through the existing
  `cached(key, QUOTES_TTL, …)` with key `quotes:` + sorted symbols joined by `,`.
- Response: `[{"symbol": "ITC", "price": 412.5, "change_pct": 1.23}]` from the last two
  non-NaN closes; a symbol with fewer than 2 closes is omitted. Order follows the request.

## Frontend

### Stock page

- `App.jsx`: `/research/stock/:symbol` → `gated(<Dashboard />)`.
- `Dashboard.jsx` reads `useParams().symbol`; when present it runs the existing `analyse(symbol)`
  flow and renders the analysis (and "Back to Research" → `/research`). When absent it renders
  the front page. Arriving at `/research` with `state.symbol` (old callers) → `navigate(
  /research/stock/${symbol}, { replace: true })`. `state.index` keeps opening the index view.
- `SmartSearch` `onSearch(symbol)` → `navigate(/research/stock/${symbol})`.
- A small `openStock(symbol)` helper (`frontend/src/utils/stocks.js`, exports
  `stockPath(symbol)` = `/research/stock/${encodeURIComponent(bareSymbol(symbol))}`) is used by:
  `Scrip` (Link `to={stockPath(symbol)}`), `ScannerPage`, `Watchlist`, `Portfolio`,
  `Market` (symbol rows), and `Dashboard`.
- Opening a stock records it in recent stocks (below).

### Front page (`/research`, no symbol)

Order: Section tabs · Search · **Recent** · **Watchlist** · **Markets**.
- **Recent**: last 8 distinct symbols opened, newest first, `localStorage` key
  `neotrade.recentStocks` (wrapped in try/catch; empty if unavailable). Chips → stock page.
  `Clear` button. Hidden when empty.
- **Watchlist**: chips from `GET /watchlist/details` — symbol, last price, day change (coloured).
  `All watchlist ›` → `/research/watchlist`. Empty: "Add stocks from a stock page with Watch."
- **Markets**: existing `<Market />` (indices + movers), no longer behind a tab.
- Removed from this page: `GuardrailAlerts`, `PortfolioGlance`, `BrokerPnl`, live engine orders
  `TradeLedger`, the Your broker / Markets tabs.

### Mine → Trades

`Journal.jsx` with `view="trades"`: `BrokerPnl` (journal data it already loads, or its own fetch
of `endpoints.journal.get`) and, when non-empty, "Live engine orders" (`TradeLedger` of
`endpoints.trading.trades(null, 'live')`, refreshed on the `trades` topic) at the top, above the
existing content. `PortfolioGlance` is not moved (Mine → Holdings covers it).

### Prices in suggestions

`SmartSearch`: after matches arrive, one `GET /market/quotes?symbols=<visible matches>`; each
row shows `₹price` and coloured `change_pct` when present. A slower quotes response for an older
query is ignored. Typing and keyboard selection never wait on it.

## Testing

`backend/tests/test_market_quotes.py` (`yf.download` patched, cache cleared per test):
- several symbols → price/change from the last two closes, request order kept;
- one symbol (flat or MultiIndex columns) works;
- a symbol with no data is omitted;
- 9 symbols → 422; empty → 422;
- second identical request is served from cache (download called once).

Frontend: `npm run build` + lint on changed files.
