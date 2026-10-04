# Research Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A URL per stock, a Research front page of search/recent/watchlist/markets, broker statement moved to Mine → Trades, prices in search suggestions.

**Architecture:** One backend endpoint (`GET /market/quotes`, batched + cached). Frontend: `stockPath()` helper used by every stock link; `Dashboard.jsx` switches on `useParams().symbol`; `Journal.jsx` (trades view) gains `BrokerPnl` + live engine orders.

**Tech Stack:** FastAPI, yfinance, pytest; React 19 + react-router + Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-research-page-design.md`

## Global Constraints

- Quotes: 1–8 symbols, upper-cased, de-duplicated; else 422. Cache key `quotes:` + sorted symbols joined by `,`, TTL `QUOTES_TTL`. Response order = request order; symbols with < 2 closes omitted.
- Recent stocks: `localStorage` key `neotrade.recentStocks`, max 8, every access in try/catch.
- Index views stay state-based.
- Frontend check: `npm run build` + `npx eslint <changed files>`.

## Review Focus

1. **Symbol with `&` or `-` (M&M, BAJAJ-AUTO)** → URL-encoded in `stockPath`, decoded by the route, analysis loads. Task 2.
2. **Old caller still navigating `/research` with `state.symbol`** → redirected to the stock URL, not a blank front page. Task 2.
3. **Private window / storage blocked** → Recent hidden, page works. Task 2.
4. **Quotes response for an older query arrives late** → ignored. Task 2.
5. **yfinance returns nothing at all for the quote batch** → `[]`, suggestions still usable. Task 1 test.

---

### Task 1: `GET /market/quotes`

**Files:** Modify `backend/routers/market_data.py`. Test: `backend/tests/test_market_quotes.py`.

**Interfaces:** Produces `GET /market/quotes?symbols=A,B` → `list[{"symbol": str, "price": float, "change_pct": float}]`; helper `_quotes_sync(symbols: list[str]) -> list[dict]`.

- [ ] **Step 1: Failing tests** (`monkeypatch.setattr(market_data.yf, "download", fake)`; clear the `cached` store between tests via whatever `backend/market_cache.py` exposes, else use unique symbol sets per test)

```python
def test_quotes_from_last_two_closes_in_request_order()   # ITC 400→410, INFY 1500→1485 → [{"symbol":"INFY",...,-1.0}, {"symbol":"ITC",...,2.5}] for symbols=INFY,ITC
def test_single_symbol()                                  # flat columns → one row
def test_symbol_without_data_is_omitted()                 # GONE all NaN → absent
def test_nothing_at_all_is_empty_list()                   # empty frame → []
def test_more_than_eight_or_none_is_422()
def test_identical_request_is_cached()                    # download called once for two calls
```

- [ ] **Step 2: Run, verify fail** — `python3 -m pytest backend/tests/test_market_quotes.py -q -p no:cacheprovider`
- [ ] **Step 3: Implement** in `market_data.py` (`Query` string param, validation → `HTTPException(422)`, `cached("quotes:"+",".join(sorted(syms)), QUOTES_TTL, lambda: asyncio.to_thread(_quotes_sync, syms))`). Handle MultiIndex and flat column results.
- [ ] **Step 4: Run file + full suite, PASS.**
- [ ] **Step 5: Commit** `feat(research): batched, cached quotes for search suggestions`

---

### Task 2: Stock URLs, front page, Mine → Trades, suggestion prices

**Files:** Create `frontend/src/utils/stocks.js` (`stockPath(symbol)`, `recentStocks()`, `rememberStock(symbol)`, `clearRecentStocks()`). Modify `App.jsx`, `pages/Dashboard.jsx`, `components/dashboard/SmartSearch.jsx`, `components/doc/Doc.jsx` (`Scrip`), `pages/ScannerPage.jsx`, `pages/Watchlist.jsx`, `pages/Portfolio.jsx`, `components/dashboard/Market.jsx`, `pages/Journal.jsx`, `utils/api.js` (`market.quotes(symbols)`).

- [ ] **Step 1:** `stocks.js` helpers per Global Constraints; `stockPath` = `/research/stock/${encodeURIComponent(bareSymbol(symbol))}`.
- [ ] **Step 2:** Route `/research/stock/:symbol` → `gated(<Dashboard />)`; `Dashboard` uses `useParams` (decode), runs `analyse` on symbol change, records recent, "Back to Research"; `/research` + `state.symbol` → replace-navigate to `stockPath`; front page = search, Recent, Watchlist chips (`/watchlist/details`), `<Market />`; remove `GuardrailAlerts`, `PortfolioGlance`, `BrokerPnl`, live `TradeLedger`, tabs and their now-unused state/fetches.
- [ ] **Step 3:** Every stock link via `stockPath` (Scrip `Link to`, Scanner, Watchlist, Portfolio, Market symbol rows); `SmartSearch` selection navigates to `stockPath` (Dashboard passes it).
- [ ] **Step 4:** `Journal.jsx` trades view: `BrokerPnl` (journal it already loads) + live engine orders `TradeLedger` (own fetch, `useTopic('trades')`), above existing content.
- [ ] **Step 5:** `SmartSearch` prices: after matches set, request quotes for their symbols with a request counter; rows show price + coloured change when present.
- [ ] **Step 6:** `cd frontend && npm run build && npx eslint <changed files>` → build OK, no new errors.
- [ ] **Step 7: Commit** `feat(research): a URL per stock; front page of search, recent, watchlist and markets; broker statement on Mine -> Trades`
