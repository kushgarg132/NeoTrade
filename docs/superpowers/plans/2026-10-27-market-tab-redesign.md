# Market tab redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/market` answers "what is the market doing and why" first, with tabs Today / Sectors / News / Watchlist.

**Architecture:** Two small backend additions (index intraday points; a `news` flag on scan movers). Pure helpers in
`utils/market.js`. One component per tab under `components/market/`; `pages/Market.jsx` wires them and retires
`Pulse.jsx`. Each tab gets an impeccable polish/audit pass before commit.

**Tech Stack:** FastAPI, yfinance, Motor; React 19, recharts, Tailwind v4 tokens, node:test.

**Spec:** `docs/superpowers/specs/2026-10-27-market-tab-redesign-design.md`

## Global Constraints

- Tabs `today` (default) | `sectors` | `news` | `watchlist`; `?tab=pulse` -> `today` via `useTabParam(ids, 'today', 'tab', alias)` (alias arg exists in `ui/Tabs.jsx`).
- Breadth words by up share `up/n`: >= 0.7 "Broad rally"; >= 0.55 "Leaning up"; > 0.45 "Mixed"; > 0.3 "Leaning down"; else "Broad sell-off".
- Impact words: >= 7 "High"; >= 4 "Med"; else "Low".
- Movers: 5 gainers, 5 losers. Events: up to 5. Index tiles: `^NSEI`, `^NSEBANK`, `^BSESN`; the rest under "More indices".
- Intraday route caches 60 s in-process per ticker; 404 untracked ticker; 502 no points. Points `[{t, close}]`.
- Movers `news`: a SCORED `news_items` doc with an impact `{type: "symbol", target: <symbol>}` published in the last 24 h.
- `GET /market/scan` response has no `movers` key; the cache entry keeps it (sector page reads it).
- Market closed: headings say "Last session" (use `utils/formatters` phase helpers already used by Pulse/AsOf).
- DESIGN.md tokens only; tabular figures; gain/loss colour only for direction; 44 px touch targets; charts via recharts + `ui/chartTheme`.
- No new AI calls or prompts; detail pages (index, sector, news item, stock) unchanged.
- Backend tests: `docker run --rm -v <abs repo path>:/src -w /src --entrypoint python neotrade-verify:main -m pytest -q -p no:cacheprovider <path>`.
- Frontend: in `frontend/`: `npm run lint && npm test && npm run build`.
- Implementers do not edit `docs/wiki/*` or `frontend/src/handbook/*` (Task 6 owns docs).

## Review Focus

1. Index with no intraday data (weekend start, yfinance hiccup): the tile still shows level and % with no sparkline, not an error — Task 3 source test `tile renders without points`; Task 1 502 test.
2. Breadth `n = 0` (feed down): no word, no divide-by-zero — Task 2 `breadthWord({up:0,n:0})` returns `''`.
3. Sector with `sentiment == null`: no news dot, sorts last under News sort — Task 2 `sortSectors` test.
4. News published just before IST midnight is not "Material today" — Task 2 `materialToday` IST boundary test.
5. News query failure on scan: movers still render with `news: false` — Task 1 test.

---

### Task 1: Backend — index intraday, movers `news`, no `movers` in scan response

**Files:**
- Modify: `backend/routers/market_data.py` (new route next to `get_index_detail`; `get_market_scan`)
- Test: `backend/tests/test_market_detail_routes.py` (extend; follow its fixtures)

**Interfaces:**
- Produces: `GET /api/v1/market/index/{ticker}/intraday -> [{"t": ISO str, "close": float}]`;
  scan rows in `gainers`/`losers` carry `"news": bool`; scan response without `movers`.

- [ ] **Step 1: Failing tests**

```python
def test_index_intraday_returns_points_for_a_tracked_index(...)   # patch the yfinance fetch -> 3 rows; 200, len 3, keys {"t","close"}
def test_index_intraday_404_for_an_untracked_ticker(...)
def test_index_intraday_502_when_no_points(...)
def test_scan_movers_flag_news_in_the_last_24h(...)    # news_items: SCORED impact symbol TCS 2 h ago -> TCS news True; INFY none -> False
def test_scan_movers_news_false_when_the_news_query_fails(...)
def test_scan_response_has_no_movers_key(...)
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement** — `_fetch_index_intraday_sync(ticker) -> list[dict]` (yfinance `history(period="1d", interval="5m")` on the ticker as-is, like `_fetch_index_detail_sync`), `asyncio.to_thread`, module-level dict cache `{ticker: (monotonic, points)}` 60 s. In `get_market_scan` after the cached read: copy the dict without `movers`; one `find` over `{status: SCORED, published_at >= now-24h, impacts: {$elemMatch: {type: "symbol", target: {$in: symbols}}}}` projecting `impacts`, set `news` on each gainer/loser (copies, never mutate the cache entry); any exception -> all False.
- [ ] **Step 4: Run Task 1 tests + `test_market_index_detail.py`** — pass. Full suite once.
- [ ] **Step 5: Commit** `feat(market): index intraday points, news flag on scan movers [skip ci]`

### Task 2: Pure helpers (`frontend/src/utils/market.js`)

**Files:**
- Modify: `frontend/src/utils/market.js`; Test: `frontend/src/utils/market.test.js` (create or extend)

**Interfaces:**
- Produces: `breadthWord(b: {up, n}) -> string`; `impactWord(n: number) -> 'High'|'Med'|'Low'`;
  `sortSectors(rows, by: 'move'|'news'|'breadth') -> rows` (new array; move = |change_pct| desc; news = sentiment desc, null last; breadth = up/n desc);
  `materialToday(items, now: Date) -> {pinned, rest}` (pinned = `material` and published on/after IST midnight of `now`).

- [ ] **Step 1: Failing tests** — thresholds exactly at 0.7, 0.55, 0.45, 0.3 and `{up:0,n:0}` -> `''`; `impactWord(7)`=='High', `(4)`=='Med', `(3.9)`=='Low'; `sortSectors` each key incl. null sentiment last and input not mutated; `materialToday` with an item at 18:29 UTC the previous day (23:59 IST) not pinned and one at 18:31 UTC pinned.
- [ ] **Step 2: `npm test`** — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `npm test`** — pass; `npm run lint`.
- [ ] **Step 5: Commit** `feat(market): breadth and impact words, sector sort, material today [skip ci]`

### Task 3: Today tab (`frontend/src/components/market/Today.jsx`)

**Files:**
- Create: `frontend/src/components/market/Today.jsx`, `frontend/src/components/market/Today.test.js` (source checks, like `pages/Ideas.test.js`)
- Modify: `frontend/src/utils/api.js` (`marketIndexIntraday: (t) => \`/market/index/${encodeURIComponent(t)}/intraday\``)

**Interfaces:**
- Consumes: Task 1 route and `news` flag; Task 2 `breadthWord`.
- Produces: default export `Today` (no props).

- [ ] **Step 1: Build sections in order** Story (`GET /market/brief`, regime chip, `AiMarkdown` clamped 2 lines + Read more, AsOf, "Last session" when closed, 404 Empty) -> Indices (3 tiles with recharts sparkline from `marketIndexIntraday`, tile fine without points; "More indices" disclosure rows) -> Breadth (existing `BreadthBar` moved here + `breadthWord`) -> Movers (segmented Gainers|Losers on phones, two columns `sm+`; row: symbol, % change, price, news dot when `news`; `stockPath`) -> Events today (`/today` `backdrop.events`, up to 5, hidden when empty). Reuse Pulse's `useSection`, `AsOf`, `MoverRows`, `BreadthBar` by moving them (Pulse.jsx is deleted in Task 6).
- [ ] **Step 2: Source tests** — Story before Indices; `tile renders without points` (sparkline guarded by points length); each section has Skeleton + ErrorLine + Empty; `breadthWord` used.
- [ ] **Step 3: Impeccable pass** — invoke the `impeccable:impeccable` skill (polish + audit) on `Today.jsx`; apply fixes within DESIGN.md tokens.
- [ ] **Step 4: `npm run lint && npm test && npm run build`** — pass.
- [ ] **Step 5: Commit** `feat(market): Today tab, story first [skip ci]`

### Task 4: Sectors tab (`frontend/src/components/market/Sectors.jsx`)

**Files:**
- Create: `frontend/src/components/market/Sectors.jsx`, `frontend/src/components/market/Sectors.test.js`

**Interfaces:**
- Consumes: Task 2 `sortSectors`; `/market/scan` `sectors`, `near_high`, `near_low`.
- Produces: default export `Sectors` (no props).

- [ ] **Step 1: Build** — heat map (move content of Pulse's "Sectors today" cells: `heatColor`, "N of M up", news dot, `divergence` flag, `sectorPath` link), Sort segmented Move|News|Breadth (default Move), Extremes (Pulse's 52-week content moved). No `newsFeed` SECTOR read.
- [ ] **Step 2: Source tests** — sort control has the three labels; no `newsFeed` import; cells link `sectorPath`.
- [ ] **Step 3: Impeccable pass** on `Sectors.jsx`.
- [ ] **Step 4: lint, test, build** — pass.
- [ ] **Step 5: Commit** `feat(market): Sectors tab, one heat map with news mood [skip ci]`

### Task 5: News and Watchlist restyle

**Files:**
- Modify: `frontend/src/components/market/News.jsx`, `frontend/src/components/market/Watchlist.jsx`
- Test: `frontend/src/components/market/News.test.js` (source checks)

**Interfaces:**
- Consumes: Task 2 `impactWord`, `materialToday`.

- [ ] **Step 1: News** — row left bar (3 px, gain/loss/muted by the strongest impact's direction), `impactWord` instead of `n/10`, "Material today" group from `materialToday(items, new Date())` above the rest; scope chips, My names, socket refresh, `newsPath` links unchanged.
- [ ] **Step 2: Watchlist** — rows in the movers style (symbol, price, day %; no news dot: `/watchlist/details` rows carry no news flag); remove control kept; Empty "Track a stock" whose action renders the existing `dashboard/SmartSearch` (`compact`, `onSearch` navigates to `stockPath(symbol)`, where the Stock page's watchlist toggle adds it).
- [ ] **Step 3: Source tests** — News uses `impactWord` and `materialToday`, no `/10`; Watchlist Empty contains `SmartSearch`.
- [ ] **Step 4: Impeccable pass** on both files; then lint, test, build.
- [ ] **Step 5: Commit** `feat(market): News and Watchlist restyle [skip ci]`

### Task 6: Wire the tabs, retire Pulse, docs

**Files:**
- Modify: `frontend/src/pages/Market.jsx`; Delete: `frontend/src/components/market/Pulse.jsx` (and any test that reads it — move its assertions to Today/Sectors tests)
- Docs: `docs/wiki/frontend.md`, `docs/wiki/platform.md`, `docs/wiki/data-ai-jobs.md`, `frontend/src/handbook/jobs-and-ops.md`

- [ ] **Step 1: Market.jsx** — tabs per Global Constraints with the `pulse` alias; render `Today`, `Sectors`, `News`, `Watchlist`. Test in `pages/Market.test.js`: ids order and the alias.
- [ ] **Step 2: Remove Pulse.jsx**; `grep -rn "market/Pulse" frontend/src` returns nothing.
- [ ] **Step 3: Docs** — Market flow, new route, scan `news` / no `movers`; `verified_at` = this commit's parent on touched wiki pages; `python3 docs/wiki/stale.py` -> "wiki current".
- [ ] **Step 4: lint, test, build; full pytest.**
- [ ] **Step 5: Commit** `feat(market): Today / Sectors / News / Watchlist tabs; Pulse retired [skip ci]`

## Waves

- Wave 1: Task 1, Task 2.
- Wave 2: Task 3, Task 4, Task 5 (separate files; each moves only the Pulse pieces it needs by copying; Pulse stays until Task 6).
- Wave 3: Task 6. Then final review and deploy (backend + ingest + jobs; Vercel on push).
