# Drill-down Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every card or row that names a strategy, trade, round trip, index, sector or news item opens its own detail page under its tab.

**Architecture:** One building-blocks task adds `Card to/more`, `PageHeader backLabel`, route builders, endpoint entries, and registers six routes against stub pages. Three backend tasks add small user-scoped reads. Three frontend tasks fill the stubs and wire the links. A sweep task links the remaining cards.

**Tech Stack:** FastAPI + motor (tests: pytest, mongomock_motor, FastAPI TestClient), React 19 + react-router + Tailwind (tests: `node:test` source-contract and pure-function tests, `npm run build`).

**Spec:** `docs/superpowers/specs/2026-10-27-drill-down-navigation-design.md`

## Global Constraints

- Backend tests run in the prod image (py3.11), from the repo root:
  `docker run --rm --network none -v "$PWD/backend:/app/backend" -v "$PWD/pytest.ini:/app/pytest.ini:ro" -w /app neotrade-backend python -m pytest <paths> -q -p no:cacheprovider`
- Frontend: `cd frontend && npm test -- <file>` per file, then `npm run build` (vitest/node:test are not a build check).
- Every new endpoint sits behind `get_current_user` and filters on `user.id`; another user's id returns 404, never 403.
- Tokens only, no raw hex (DESIGN.md). Every data section: `Skeleton` loading, `ErrorLine` with Retry, `Empty` naming what fills it; a 404 shows "Not found" plus a link to the parent.
- Money the user owns carries the `private` class.
- Route segments are always built with `encodeURIComponent` via the builders in Task 1, never by string concatenation in components.
- A code change updates its wiki page section (`docs/wiki/frontend.md`, `platform.md`, `trading-engine.md`, `mine-portfolio-journal.md`, `data-ai-jobs.md`) and `verified_at` in the same commit.
- STRICT: subagents commit on their worktree branch only. No `git push`. The lead merges and pushes.

## Review Focus

1. Names with reserved characters in the URL: `picks:pullback`, `^NSEI`, `Oil & Gas`, journal ids like `u1:kite:123`. They must round-trip through the builders and `useParams` unchanged.
2. Another user's trade, round trip or a made-up id must 404, not leak or 500.
3. An open trade (no `exit_at`, no `realized_pnl`) on `/ai/trade/:id` and an open round trip (`pnl: null`) must render "Open" rather than crash or show ₹0.
4. A news item not yet scored has no `news_outcomes` rows: the page shows "Not scored yet", not an error.
5. A strategy name in the URL that has no scorecard row and no backtest (e.g. a typo) shows "No trades yet" and the backtest empty state, not a blank page.

Each line has its test in the owning task (marked **RF1** to **RF5**).

## Waves

- **Wave 1 (parallel, separate worktrees):** Task 1, Task 2, Task 3, Task 4. No shared files.
- **Wave 2 (parallel):** Task 5, Task 6, Task 7. Each owns its own pages and components; all route and endpoint entries already exist from Task 1.
- **Wave 3:** Task 8, then the deploy step.

---

### Task 1: Building blocks and route stubs

**Files:**
- Modify: `frontend/src/utils/routes.js`, `frontend/src/utils/routes.test.js`
- Modify: `frontend/src/utils/api.js` (`endpoints`), `frontend/src/utils/endpoints.test.js`
- Modify: `frontend/src/components/ui/Card.jsx`, `frontend/src/components/ui/PageHeader.jsx`
- Create: `frontend/src/components/ui/Card.test.js`
- Modify: `frontend/src/components/layout/tabs.js` (Market lights on `/news/*`)
- Create stubs: `frontend/src/pages/AiStrategy.jsx`, `AiTrade.jsx`, `RoundTrip.jsx`, `IndexPage.jsx`, `SectorPage.jsx`, `NewsItem.jsx`
- Modify: `frontend/src/App.jsx` (six `gated(...)` routes, lazy imports like the others)
- Modify: `docs/wiki/frontend.md` (Routes table, Card/PageHeader in shared components)

**Interfaces:**
- Produces, in `utils/routes.js`:
  `strategyPath(name: string) => '/ai/strategy/' + enc`, `aiTradePath(id)`, `roundTripPath(id) => '/money/trade/' + enc`,
  `indexPath(ticker) => '/market/index/' + enc`, `sectorPath(name) => '/market/sector/' + enc`, `newsPath(id) => '/news/' + enc`.
  `ROUTES` gains `/ai/strategy/:name`, `/ai/trade/:id`, `/money/trade/:id`, `/market/index/:ticker`, `/market/sector/:name`, `/news/:id`.
- Produces, in `endpoints`: `trades({ strategy, venue, status, limit })` (query string, omitting undefined), `trade(id) => '/trading/trades/' + enc`,
  `backtest(name) => '/trading/backtests/' + enc`, `roundTrip(id) => '/journal/round-trips/' + enc`,
  `marketSector(name) => '/market/sector/' + enc`, `newsItem(id) => '/news/item/' + enc`. Reuse existing `marketIndex`, `marketIndexAnalysis`.
- Produces: `<Card title action to more={{ to, label }}>`; `<PageHeader title back backLabel right>`.
- Stub page body: `<PageHeader title="…" back={<parent>} backLabel="…" />` plus `<Empty title="Coming soon" />`. Wave 2 replaces it.

- [ ] **Step 1: Write failing tests**

`routes.test.js`:
```js
test('detail builders encode every segment and match a real route', () => {
  assert.equal(strategyPath('picks:pullback'), '/ai/strategy/picks%3Apullback');
  assert.equal(indexPath('^NSEI'), '/market/index/%5ENSEI');
  assert.equal(sectorPath('Oil & Gas'), '/market/sector/Oil%20%26%20Gas');
  assert.equal(roundTripPath('u1:kite:123'), '/money/trade/u1%3Akite%3A123');
  for (const p of ['/ai/strategy/:name', '/ai/trade/:id', '/money/trade/:id', '/market/index/:ticker', '/market/sector/:name', '/news/:id'])
    assert.ok(ROUTES.includes(p), p);
}); // RF1
```
`endpoints.test.js`: `endpoints.trades({ strategy: 'picks:pullback', venue: 'paper' })` equals `'/trading/trades?strategy=picks%3Apullback&venue=paper'`; `endpoints.trades({})` equals `'/trading/trades'`.
`Card.test.js` (source contract, like `ListRow.test.js`): source matches `/to \?/` producing a `Link`, renders `ChevronRight` when `to`, and renders `more.label` inside a `Link` to `more.to`; docstring contains "never both".
Tab test in the existing tabs test (or `routes.test.js`): `tabActive({path:'/market'}, '/news/abc')` is true.

- [ ] **Step 2: Run, verify they fail**

Run: `cd frontend && npm test -- src/utils/routes.test.js src/utils/endpoints.test.js src/components/ui/Card.test.js`
Expected: FAIL (builders not exported, Card has no `to`).

- [ ] **Step 3: Implement**

Card with `to`: wrap the whole `section` content in `Link` with the `Tile` interactive classes (`hover:bg-[var(--surface-2)] active:scale-[0.98] focus-visible:ring-2 …`). With `more`: title row right side shows `<Link to={more.to}>{more.label ?? 'See all'} ›</Link>` (min-h-11 tap target). Docstring: "`to` makes the whole card one link; a card that holds links takes `more` instead, never both."
PageHeader: when `backLabel` is set, print it after the chevron (13 px, `--text-muted`), aria-label `Back to ${backLabel}`.
`tabActive`: Market also matches `pathname.startsWith('/news/')`.

- [ ] **Step 4: Run tests and build**

Run: `cd frontend && npm test && npm run build`
Expected: all pass, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src docs/wiki/frontend.md
git commit -m "feat(ui): Card to/more, PageHeader backLabel, detail routes and builders"
```

### Task 2: Backend reads for AI drill-downs

**Files:**
- Modify: `backend/engine/persistence.py` (`LedgerStore.get_trades`, new `get_trade`)
- Modify: `backend/routers/trading.py` (`GET /trades` gains `strategy`; new `GET /trades/{trade_id}`)
- Modify: `backend/analytics.py` (`compute_scorecard`: each strategy row `parked`)
- Test: `backend/tests/test_trading_router.py`, `backend/tests/test_scorecard.py`
- Modify: `docs/wiki/trading-engine.md`, `docs/wiki/platform.md` (endpoint map, scorecard fields)

**Interfaces:**
- Produces: `LedgerStore.get_trades(status=None, limit=200, venue=None, mode=None, strategy: Optional[str] = None) -> list[dict]`.
- Produces: `LedgerStore.get_trade(trade_id: str) -> Optional[dict]` (query `{"user_id": self.user_id, "id": trade_id}`, `_clean_id`).
- Produces: `GET /api/v1/trading/trades?strategy=` and `GET /api/v1/trading/trades/{trade_id}` → the trade dict, 404 `"Trade not found"`.
- Produces: scorecard `strategies[i].parked: bool` = `strategy in autopilot.fence.PARKED`.
- Add `# ponytail: paper_trades has no index; add (user_id, id) if trades pass ~50k` on `get_trade`.

- [ ] **Step 1: Write failing tests**

In `test_trading_router.py`, seed two users' `paper_trades` via mongomock and the existing TestClient pattern:
- `test_trades_filter_by_strategy`: u1 has trades `picks:pullback` and `gap_and_go`; `GET /trading/trades?strategy=picks:pullback` returns only the first.
- `test_trade_by_id_returns_the_users_trade`: 200, `body["id"] == "t1"`.
- `test_trade_by_id_of_another_user_is_404`: trade `t9` owned by `u2`, requested as `u1` → 404. **RF2**
- `test_trade_by_unknown_id_is_404`.
- `test_open_trade_by_id_has_no_exit`: an OPEN trade returns 200 with `exit_at` absent or None. **RF3**

In `test_scorecard.py`: `test_parked_strategies_are_flagged`: a closed `analyst_verdict` trade row has `parked is True`, a `gap_and_go` row `parked is False`.

- [ ] **Step 2: Run, verify they fail**

Run (prod image, see Global Constraints): `backend/tests/test_trading_router.py backend/tests/test_scorecard.py`
Expected: new tests FAIL (unknown query param ignored, 404/405 on by-id, KeyError `parked`).

- [ ] **Step 3: Implement** as in Interfaces. Declare `/trades/{trade_id}` after `/trades` and ensure no clash with other `/trades/...` routes in the file.

- [ ] **Step 4: Run tests, verify pass**

Same command, then the full `backend/tests` suite once. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend docs/wiki
git commit -m "feat(trading): trades by strategy and by id; scorecard flags parked strategies"
```

### Task 3: Backend read for a journal round trip

**Files:**
- Modify: `backend/routers/journal.py` (new `GET /round-trips/{trip_id}`)
- Create: `backend/tests/test_journal_round_trip_route.py`
- Modify: `docs/wiki/mine-portfolio-journal.md` (Endpoints)

**Interfaces:**
- Produces: `GET /api/v1/journal/round-trips/{trip_id}` → the round trip dict from `build_round_trips` (all accounts), plus `note`, `tags` from `store.notes_for`, `fills` = the `journal_trades` whose `_id` is in `trade_ids` (fields `side, quantity, price, traded_at`), `news` and `exit_news` from `attach_news`, and `insights` = entries of `build_insights(...)` whose round-trip ids include `trip_id` (match on whatever id field `build_insights` already emits; read it first).
- 404 `"Round trip not found"` when absent. Trips are built only from `store.list_trades(user.id)`, so another user's id is absent by construction.

- [ ] **Step 1: Write failing tests** (TestClient + `app.dependency_overrides[get_current_user]`, `get_journal_store` over mongomock):
- `test_round_trip_by_id`: seed a BUY then SELL for `u1` with `_id`s `u1:kite:1`, `u1:kite:2`; `GET /journal/round-trips/u1%3Akite%3A1` → 200, `pnl` equals `(sell-buy)*qty`, `len(fills) == 2`. **RF1**
- `test_open_round_trip_has_null_pnl`: only the BUY → 200, `pnl is None`. **RF3**
- `test_other_users_round_trip_is_404`: seed under `u2`, request as `u1` → 404. **RF2**

- [ ] **Step 2: Run, verify fail** (prod image, that file). Expected: 404/405 for all.
- [ ] **Step 3: Implement** reusing `build_round_trips`, `notes_for`, `attach_news`, `build_insights`; no new helpers.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit**

```bash
git add backend docs/wiki
git commit -m "feat(journal): GET one round trip with fills, note, news and findings"
```

### Task 4: Backend reads for sector and news item

**Files:**
- Modify: `backend/routers/market_data.py` (new `GET /market/sector/{name}`)
- Modify: `backend/routers/news.py` (new `GET /news/item/{item_id}`)
- Create: `backend/tests/test_market_detail_routes.py`
- Modify: `docs/wiki/platform.md`, `docs/wiki/data-ai-jobs.md`

**Interfaces:**
- Produces: `market_scan(...)` also returns `movers` (every row, sorted by `change_pct` desc; the existing lists are capped at 10, so they cannot serve a sector).
- Produces: `sector_members(scan: dict, name: str) -> list[dict]` (pure, in `market_data.py`): `scan["movers"]` filtered to `sector == name`.
- Produces: `GET /api/v1/market/sector/{name}` → `{sector, change_pct, up, n, sentiment, members: [...movers rows], news: [up to 20 FEED_FIELDS items whose impacts include {type:"sector", target:name}, newest first], at}`; 404 `"Unknown sector"` when `name` is not in `scan["sectors"]`. Sentiment via `with_sentiment` on the one sector.
- Produces: `GET /api/v1/news/item/{item_id}` → `FEED_FIELDS` of the `news_items` doc with `id`, aware `published_at`, plus `outcomes: [news_outcomes rows with _id prefix f"{item_id}:"]` (fields `type, target, direction, impact`, `ret_/bench_/move_` for `1h,1d,5d`); 404 `"News item not found"`. Market-wide data: no user filter (news is shared), still behind auth.

- [ ] **Step 1: Write failing tests**
- `test_market_scan_returns_all_movers_sorted`: pure `market_scan` with 3 rows in 2 sectors → `len(movers) == 3`, sorted desc.
- `test_sector_members_filters_by_name`: `sector_members({"movers": [...]}, "Oil & Gas")` returns only that sector. **RF1**
- `test_sector_route_unknown_is_404`: monkeypatch `cached` to return a scan without the sector → 404.
- `test_news_item_with_outcomes`: mongomock `news_items` doc `n1` + two `news_outcomes` rows `n1:symbol:TCS`, `n1:sector:IT` → 200, `len(outcomes) == 2`.
- `test_unscored_news_item_has_empty_outcomes`: doc without outcome rows → 200, `outcomes == []`. **RF4**
- `test_news_item_unknown_is_404`.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** as in Interfaces. Keep `/market/scan`'s response shape a superset (only `movers` added).
- [ ] **Step 4: Run tests, verify pass** (that file plus `backend/tests/test_market_quotes.py`).
- [ ] **Step 5: Commit**

```bash
git add backend docs/wiki
git commit -m "feat(market): sector detail and news item reads"
```

### Task 5: AI strategy and trade pages

**Files:**
- Replace stubs: `frontend/src/pages/AiStrategy.jsx`, `frontend/src/pages/AiTrade.jsx`
- Create: `frontend/src/utils/aiDetail.js`, `frontend/src/utils/aiDetail.test.js`
- Modify: `frontend/src/components/ai/Scoreboard.jsx` (rows `to={strategyPath(st.strategy)}`, drop `chevron={false}`; skip `unattributed`), `frontend/src/components/ai/Positions.jsx` (rows to `aiTradePath(p.id)` when the row has a trade id, else keep `stockPath`)
- Modify: `docs/wiki/frontend.md` (flow 7 + new pages)

**Interfaces:**
- Consumes: Task 1 builders and endpoints; Task 2 `GET /trading/trades?strategy=`, `GET /trading/trades/{id}`, scorecard `parked`; existing `GET /analytics/scorecard?venue=paper`, `useForward`/`badgeFor`, `/today` `autopilot.paused`.
- Produces (pure, `utils/aiDetail.js`):
  `strategyRow(card, name) => row | null` (the scorecard strategy whose `strategy === name`);
  `strategyStatus({ row, badge, paused }) => { label: 'Parked'|'Paused'|'Proven'|'Unproven', tone }` (parked wins, then paused, then the forward badge);
  `tradeSummary(trade) => { open: boolean, net: number|null, gross: number|null, costs: number, held: string }` (`open` when `status === 'OPEN'`; `net = realized_pnl - costs` only when closed).

- [ ] **Step 1: Write failing tests** in `aiDetail.test.js`:
- `strategyRow(card, 'nope')` is `null`. **RF5**
- `strategyStatus({ row: { parked: true }, badge: { tone: 'success' }, paused: ['x'] })` is `Parked`; paused name → `Paused`.
- `tradeSummary({ status: 'OPEN', costs: 12 })` → `{ open: true, net: null }`. **RF3**
- `tradeSummary({ status: 'CLOSED', realized_pnl: 100, costs: 12 })` → `net === 88`.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement pages**
  - AiStrategy: `PageHeader title={name} back="/ai?tab=scoreboard" backLabel="AI"`; stat row (net, open, vs NIFTY, win rate) from `strategyRow`, else `Empty "No trades yet"` (**RF5**); status `Badge` from `strategyStatus`; backtest `Card` from `endpoints.backtest(name)` (404 → `Empty "No backtest recorded"`); trades `Card` listing `endpoints.trades({ strategy: name, venue: 'paper', limit: 200 })` as `ListRow to={aiTradePath(t.id)}`.
  - AiTrade: `back={strategyPath(trade.strategy)} backLabel={trade.strategy}`; entry/exit, quantity, gross/costs/net (or "Open" badge, **RF3**), exit reason, levels from `context` (stop, target, max hold, trail), why (`context.reason_codes`, `context.score.rule/ai/final`), the Stock page's chart component with entry/exit markers, link to `stockPath(symbol)`; 404 → "Not found" + link to `/ai`.
- [ ] **Step 4: Run tests and build.** `cd frontend && npm test && npm run build`. Expected: pass.
- [ ] **Step 5: Commit**

```bash
git add frontend/src docs/wiki/frontend.md
git commit -m "feat(ai): strategy and trade drill-down pages"
```

### Task 6: Round-trip page and Money links

**Files:**
- Replace stub: `frontend/src/pages/RoundTrip.jsx`
- Modify: `frontend/src/components/money/JournalTab.jsx` (rows link to `roundTripPath(trip.id)`; the inline note editor moves to the page; keep the row's note preview)
- Modify: `frontend/src/components/money/TaxTab.jsx` (harvest rows `to={stockPath(symbol)}`), `frontend/src/components/money/OverviewTab.jsx` (top movers `to={stockPath(symbol)}` if not already)
- Create: `frontend/src/utils/roundTrip.js`, `frontend/src/utils/roundTrip.test.js`
- Modify: `docs/wiki/frontend.md` (flow 5)

**Interfaces:**
- Consumes: Task 1 `roundTripPath`, `endpoints.roundTrip`; Task 3 response shape; existing `PUT /journal/round-trips/{id}/note`, `NewsChips`.
- Produces: `holdTime(opened_at, closed_at|null, now) => string` ("3 days", "2 h", "Open · 5 days").

- [ ] **Step 1: Failing tests:** `holdTime` for closed (2 days), same-day (hours), open (prefixed "Open"). **RF3**
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement page:** `back="/money?tab=journal" backLabel="Journal"`; fills list, average entry/exit, hold time, P&L (`private`; "Open" when `pnl === null`), note + tags editor (same PUT), `NewsChips` for `news`/`exit_news`, insights list, link to stock; 404 → "Not found" + link to journal.
- [ ] **Step 4: Run tests and build.**
- [ ] **Step 5: Commit**

```bash
git add frontend/src docs/wiki/frontend.md
git commit -m "feat(money): round-trip page; journal, tax and movers rows link through"
```

### Task 7: Index, sector and news item pages

**Files:**
- Replace stubs: `frontend/src/pages/IndexPage.jsx`, `SectorPage.jsx`, `NewsItem.jsx`
- Modify: `frontend/src/components/market/Pulse.jsx` (Indices rows → `indexPath`, Sectors today and Sector news mood rows → `sectorPath`; the "Why X moved" card `to={indexPath(...)}`)
- Modify: the News tab list component and `components/stock/NewsChips` (or wherever the chip renders) → `newsPath(id)` when the item has an `id`; external article link moves to the news page
- Create: `frontend/src/utils/newsItem.js`, `frontend/src/utils/newsItem.test.js`
- Modify: `docs/wiki/frontend.md` (flow 8)

**Interfaces:**
- Consumes: Task 1 builders/endpoints; Task 4 shapes; existing `marketIndex`, `marketIndexAnalysis`.
- Produces: `outcomeRows(outcomes) => [{ target, horizon: '1h'|'1d'|'5d', move, vsBench }]` skipping missing horizons; `[]` for none.

- [ ] **Step 1: Failing tests:** `outcomeRows([])` is `[]` (**RF4**); a row with only `ret_1d`/`bench_1d` yields one `1d` entry with `vsBench = ret - bench`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement pages:**
  - IndexPage: `back="/market?tab=pulse" backLabel="Market"`; chart from `marketIndex(ticker)`, `AiCard` "Why it moved" from `marketIndexAnalysis(ticker)`.
  - SectorPage: header change %, up/n, sentiment; members `ListRow to={stockPath}` sorted by move; news rows `to={newsPath(id)}`; 404 → "Unknown sector".
  - NewsItem: `back="/market?tab=news" backLabel="News"`; title, source, time, impacts (target, direction arrow + signed impact /10, target links to stock or sector), outcomes via `outcomeRows` or "Not scored yet" (**RF4**), "Read article" external link.
- [ ] **Step 4: Run tests and build.**
- [ ] **Step 5: Commit**

```bash
git add frontend/src docs/wiki/frontend.md
git commit -m "feat(market): index, sector and news item pages; Pulse and news link through"
```

### Task 8: Sweep the remaining dead-end cards

**Files:**
- Modify: `frontend/src/pages/Home.jsx` / `components/home/*` (BriefCard `more` → `/market?tab=pulse` pre-open, `/money` after close), `frontend/src/pages/WeeklyReport.jsx` (AI section `to="/ai"`, journal `to="/money?tab=journal"`, best/worst rows `to={stockPath}`), `frontend/src/components/stock/AnalysisTab.jsx` (each card's natural target: news card → Stock `?tab=news`, events → `?tab=events`), `frontend/src/components/money/TaxTab.jsx` cards without inner links → holding's stock
- Modify: `frontend/src/handbook/*.md` routes/navigation section; `docs/wiki/frontend.md`

**Interfaces:** Consumes Task 1 `Card to/more` and builders. Rule: a card with inner links takes `more`, never `to`.

- [ ] **Step 1: Failing test:** extend `Card.test.js` with a source scan over `src/**/*.jsx`: no file passes both `to=` and `more=` to the same `<Card`. (Regex over each `<Card ...>` opening tag.)
- [ ] **Step 2: Run, verify** it passes before the sweep and keeps passing after (a guard, not a red test; note this in the commit).
- [ ] **Step 3: Apply** `to`/`more` per the list above; leave cards with no target plain.
- [ ] **Step 4: Run** `cd frontend && npm test && npm run build`, and the handbook test (`src/utils/handbook.test.js`).
- [ ] **Step 5: Commit**

```bash
git add frontend docs/wiki/frontend.md
git commit -m "feat(ui): link the remaining dead-end cards"
```

### Deploy (lead, after Task 8 merges)

- [ ] Full backend suite in the prod image; `cd frontend && npm test && npm run build`.
- [ ] `python3 docs/wiki/stale.py` exits 0.
- [ ] Push per the session's deploy mode (ask once if not yet asked). Direct: HEAD subject ends `[skip ci]`; `cd /home/ubuntu/deploys/NeoTrade && git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend` (jobs and ingest unchanged by this work: no rebuild). Vercel builds the frontend on push.
- [ ] Verify: `curl -s -o /dev/null -w '%{http_code}' https://neotrade.161.118.167.148.nip.io/health` is 200; an authenticated `GET /api/v1/trading/trades?strategy=gap_and_go&venue=paper` returns a list.
