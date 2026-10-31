# Price Chart Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Recharts close-line `TradingChart` with a lightweight-charts chart that has
candles, volume, a crosshair readout, pan/zoom, cleaner markers and a news strip, on both the
Stock and Index pages. The feeds carry OHLCV.

**Architecture:**
- Backend changes are additive: OHLCV on index points and intraday rows, a `days=1|5` intraday
  window, and `mine.stock` returning `bars`.
- Frontend:
  - pure helpers in `utils/stock.js` (tested with `node:test`);
  - a thin canvas wrapper `PriceCanvas.jsx` around lightweight-charts;
  - a `NewsStrip.jsx`;
  - `TradingChart.jsx` orchestrating fetch, range, controls and readout.
  - Callers keep the same props.

**Tech Stack:** FastAPI + pytest, React 19 + Vite, `lightweight-charts` v5, `node --test`
(frontend tests are source/pure-function tests, no jsdom).

**Spec:** `docs/superpowers/specs/2026-10-31-price-chart-redesign-design.md`

## Global Constraints

- Ranges: `1D 1W 1M 6M 1Y 5Y`.
  - 1D = intraday `days=1` (5m).
  - 1W = intraday `days=5` (15m).
  - 1M/6M/1Y/5Y = last 22/126/252/1260 daily bars.
- Intraday `days` accepts only 1 or 5 (default 1); anything else returns 422.
- Chart height: 320 px phone, 420 px from `sm:`. Volume takes the bottom ~20% (`scaleMargins {top: 0.8, bottom: 0}`).
- Intraday polls every 60 s (`INTRADAY_POLL_MS = 60_000`), only while 1D or 1W is selected.
- Colours come only from CSS tokens (`--gain --loss --text-muted --border --surface --accent --text`),
  resolved to `rgb()` at runtime and re-applied on theme change.
- Trade identity is never colour alone: buy = `arrowUp` belowBar with text `B`, sell = `arrowDown` aboveBar with text `S`.
- Stop/target: dashed price lines, daily ranges only. Their **amounts stay under hide-amounts**:
  - the canvas axis label is hidden when `usePrivacy()` is true;
  - the HTML legend keeps `<span className="private">{l.amount}</span>`.
- Index pages pass `newsUrl={null}` and show no news (unchanged).
- Controls are `<button>` with `aria-pressed`, `min-h-11`. The chart container keeps `role="img"`
  with a text summary.
- Do not stage the unrelated `frontend/src/pages/Strategies.jsx` change or `.claude/`/`.superpowers/`.
- Docs in the same commit as the code they describe:
  - `frontend/src/handbook/trading-and-money.md` (TradingChart anchor);
  - `docs/wiki/frontend.md` (section + `verified_at`);
  - run `python3 docs/wiki/stale.py`.

## Review Focus

1. **Unsorted or duplicate intraday timestamps** (yfinance sometimes repeats the last 5m bar).
   lightweight-charts throws on non-ascending time, so `toBars` must sort ascending and keep the
   last row per time. Test in Task 3.
2. **NaN rows from yfinance** (holiday half-sessions, a missing Close). The backend must drop them,
   because Starlette would emit literal `NaN` and the browser's `JSON.parse` fails. The frontend
   `toBars` drops non-finite closes too. Tests in Task 1 and Task 3.
3. **Hide-amounts on.** Stop/target amounts must not appear in the canvas axis labels. Source test
   in Task 5.
4. **Close-only input** (`AiTrade`, or `mine.bars` older than the deploy). The chart must render as
   area with the candle toggle disabled and no volume, not blank candles. Test in Task 3.
5. **Weekend/holiday 1D.** The session is the last trading day. The previous close is the last daily
   bar *before* that session date, never the session's own bar. Test in Task 3.

---

### Task 1: Index feeds carry OHLCV; intraday `days` window

**Files:**
- Modify: `backend/datalayer/stock_info.py` (add constant)
- Modify: `backend/routers/market_data.py:177-250` (`_fetch_index_detail_sync`, `_fetch_index_intraday_sync`, `get_index_intraday`)
- Test: `backend/tests/test_market_index_detail.py`, `backend/tests/test_market_detail_routes.py`

**Interfaces:**
- Produces:
  - `backend.datalayer.stock_info.INTRADAY_WINDOWS: dict[int, tuple[str, str]] = {1: ("1d", "5m"), 5: ("5d", "15m")}` (period, interval);
  - `_fetch_index_intraday_sync(ticker: str, days: int = 1) -> list[dict]` with rows `{t, open, high, low, close, volume}`;
  - `GET /market/index/{ticker}/intraday?days=1|5`;
  - index `points` rows `{date, open, high, low, close, volume}`.

- [ ] **Step 1: Write the failing tests**
  - `test_market_index_detail.py`:
    - extend `_FakeTicker` to build `Open/High/Low/Close/Volume` columns;
    - `test_points_carry_ohlcv`: `set(r.json()["points"][0]) == {"date", "open", "high", "low", "close", "volume"}`;
    - `test_nan_rows_are_dropped`: one `Close` is `float("nan")`, so `len(points) == n - 1` and the response is valid JSON.
  - `test_market_detail_routes.py`:
    - update the existing monkeypatches to `lambda t, days=1: rows` and the key assertion to the OHLCV set;
    - `test_index_intraday_days_5_has_its_own_cache_entry`: call `?days=1` then `?days=5`. The fake
      records `(t, days)`, so `calls == [("^NSEI", 1), ("^NSEI", 5)]`;
    - `test_index_intraday_bad_days_is_422`: `?days=2` returns 422.
- [ ] **Step 2: Run, expect FAIL**
  `cd backend && python -m pytest tests/test_market_index_detail.py tests/test_market_detail_routes.py -q`
- [ ] **Step 3: Implement**
  - Add `INTRADAY_WINDOWS` to `stock_info.py`.
  - In both index fetchers, emit OHLCV and skip rows where `Close` is NaN (`pd.isna`). Volume NaN becomes `0.0`.
  - In `get_index_intraday(ticker, days: int = 1)`:
    - `days not in INTRADAY_WINDOWS` raises `HTTPException(422)`;
    - `_intraday_cache` is keyed `(ticker, days)`.
  - Update the endpoint docstring.
- [ ] **Step 4: Run, expect PASS** (same command, then the full `python -m pytest -q` in the background).
- [ ] **Step 5: Commit** `feat(market): index points and intraday carry OHLCV; intraday days=1|5`

### Task 2: Stock intraday `days`; `mine.stock` returns `bars`

**Files:**
- Modify: `backend/routers/agents.py:34-41`, `backend/mine/stock.py:64,112`
- Test: create `backend/tests/test_stock_intraday_days.py`; modify `backend/tests/test_mine_stock.py`

**Interfaces:**
- Consumes: `INTRADAY_WINDOWS` (Task 1).
- Produces:
  - `GET /agents/intraday/{symbol}?days=1|5` (PriceCandle JSON list, unchanged shape);
  - `mine.stock` response key `bars: [{date, open, high, low, close, volume}]`, replacing `closes`.

- [ ] **Step 1: Write the failing tests**
  - `test_stock_intraday_days.py`: monkeypatch `backend.datalayer.stock_info.fetch_price_history_logic`
    to record `(period, interval)` and return `([], "x")`.
    - `?days=5` records `("5d", "15m")`;
    - no param records `("1d", "5m")`;
    - `?days=3` returns 422.
    - Mount `agents.router` the way neighbouring router tests do, and override auth if the router needs it.
  - `test_mine_stock.py::test_bars_are_ohlcv`: monkeypatch `backend.mine.stock.bars.read` to return
    `{"INFY": DataFrame(open/high/low/close/volume, DatetimeIndex 2 days)}`. Assert that
    `r.json()["bars"][0]` keys equal the OHLCV set with `date` as `YYYY-MM-DD`, and that `"closes" not in r.json()`.
- [ ] **Step 2: Run, expect FAIL** `cd backend && python -m pytest tests/test_stock_intraday_days.py tests/test_mine_stock.py -q`
- [ ] **Step 3: Implement**
  - In `intraday_candles(symbol, days: int = 1)`, look up the window with the same 422 guard.
  - In `mine/stock.py`, build `bars` from the frame's five columns. The `last` fallback reads `bars[-1]["close"]`.
- [ ] **Step 4: Run, expect PASS**; full backend suite in the background.
- [ ] **Step 5: Commit** `feat(mine,agents): stock intraday days window; mine.stock returns OHLCV bars`

### Task 3: Pure chart helpers

**Files:**
- Modify: `frontend/src/utils/stock.js`
- Test: `frontend/src/utils/stock.test.js`

**Interfaces:**
- Produces (all exported from `utils/stock.js`):
  - `RANGES: Array<[label, {days: 1|5} | number]>`, equal to `[['1D',{days:1}],['1W',{days:5}],['1M',22],['6M',126],['1Y',252],['5Y',1260]]`.
  - `toBars(rows, {daily}: {daily: boolean}) -> {bars: Bar[], ohlc: boolean}`.
    - `Bar = {date, open, high, low, close, volume}`.
    - `date` comes from `r.date ?? r.timestamp ?? r.t`, cut to 10 chars when `daily`.
    - Non-finite close rows are dropped. Rows are sorted ascending by date, and the last one wins per date.
    - `ohlc` is true only if every bar has finite open/high/low.
    - When OHLC is missing, `open/high/low` fall back to `close`; volume falls back to `null`.
  - `visibleRanges(dailyCount: number) -> string[]`.
    - 1D and 1W are always included.
    - A daily chip is included only if `dailyCount` exceeds the previous daily chip's bar count (1M needs ≥ 2).
  - `prevClose(dailyBars: Bar[], sessionDate: 'YYYY-MM-DD') -> number|null`: close of the last bar with `date < sessionDate`.
  - `rangeChange(bars: Bar[]) -> {abs: number, pct: number}|null`: last close minus first close.
  - `chartTime(date: string) -> string|number`.
    - A 10-char date is returned unchanged (business day).
    - Anything else becomes `Math.floor(Date.parse(date)/1000) + 19800` (IST shown on a UTC axis).
  - `tradeMarkers` / `newsMarkers` stay as they are (keyed on `date`/`close`; `Bar` satisfies both).

- [ ] **Step 1: Write the failing tests** (`node:test`, `assert/strict`)
  - `toBars: candles pass through and ohlc is true`.
  - `toBars: close-only rows give ohlc false, open=high=low=close, volume null`.
  - `toBars: unsorted and duplicate intraday times are sorted and deduped, last row wins`.
  - `toBars: NaN or null close rows are dropped`.
  - `toBars: daily cuts PriceCandle timestamps to YYYY-MM-DD; index rows read t`.
  - `visibleRanges`:
    - `visibleRanges(250)` is `['1D','1W','1M','6M','1Y']`;
    - `visibleRanges(1300)` includes `'5Y'`;
    - `visibleRanges(1)` is `['1D','1W']`.
  - `prevClose`: for bars dated 10-29, 10-30, 10-31 with session `'2026-10-31'`, it returns the 10-30 close.
    It returns `null` when no earlier bar exists.
  - `rangeChange`: `[100 … 110]` gives `{abs: 10, pct: 10}`, and `[]` gives `null`.
  - `chartTime`:
    - `'2026-10-31'` is unchanged;
    - `'2026-10-31T09:15:00+05:30'` gives `Date.parse(...)/1000 + 19800`.
- [ ] **Step 2: Run, expect FAIL** `cd frontend && node --test src/utils/stock.test.js`
- [ ] **Step 3: Implement** the six exports above.
- [ ] **Step 4: Run, expect PASS** (same command).
- [ ] **Step 5: Commit** `feat(stock): chart helpers: toBars, ranges, prevClose, rangeChange, chartTime`

### Task 4: `PriceCanvas` and `NewsStrip` components

**Files:**
- Modify: `frontend/package.json` (`npm i lightweight-charts@^5`)
- Create: `frontend/src/components/stock/PriceCanvas.jsx`, `frontend/src/components/stock/NewsStrip.jsx`
- Test: create `frontend/src/components/stock/PriceCanvas.test.js` (source assertions, same style as `pages/Stock.test.js`)

**Interfaces:**
- Consumes: `chartTime` (Task 3).
- Produces:
  - `<PriceCanvas bars ohlc mode markers priceLines baseline hidePrices onCrosshair onPickDate />`.
    - `mode: 'candle'|'area'`.
    - `markers: [{date, kind: 'buy'|'sell'|'news', direction?, impact?}]`.
    - `priceLines: [{price, tone: 'gain'|'loss', title}]`.
    - `baseline: number|null` is the dotted previous-close line.
    - `hidePrices: boolean` hides the price-line axis labels and titles.
    - `onCrosshair(bar|null)`.
    - `onPickDate(date)` fires on a click whose bar has a news marker.
  - `<NewsStrip mark={{date, items}} onClose />`, a horizontal `overflow-x-auto snap-x` row of cards.
    - Each card shows the `NewsGlyph`-style direction mark, title (`NewsLink` when `id||url`),
      source (`utils/newsItem.js::sourceName`), and time (`formatDateTime`).
    - It also renders `ImpactChips`.
    - The region is labelled `News on {date}`.

- [ ] **Step 1: Write the failing source test**
  - `PriceCanvas.jsx`:
    - imports from `'lightweight-charts'`;
    - uses `createSeriesMarkers`, `CandlestickSeries`, `AreaSeries` and `HistogramSeries`;
    - contains `vertTouchDrag: false`, `axisLabelVisible: !hidePrices` and `LineStyle.Dashed`;
    - calls `chart.remove()` in cleanup;
    - creates a `MutationObserver` (theme re-apply).
  - `NewsStrip.jsx` contains `overflow-x-auto` and `aria-label={\`News on`.
- [ ] **Step 2: Run, expect FAIL** `cd frontend && node --test src/components/stock/PriceCanvas.test.js`
- [ ] **Step 3: Implement**
  - Create the chart once per mount with `createChart(el, {autoSize: true, ...})`.
  - Grid: horizontal lines only, `--border` colour.
  - Right price scale; `handleScroll: {vertTouchDrag: false}` so the page still scrolls on phones.
  - `dblclick` runs `timeScale().fitContent()`.
  - Series by mode:
    - `candle`: `CandlestickSeries` with up `--gain`, down `--loss`, wick same.
    - `area`: `AreaSeries` with line = the range tone, top colour = tone at 25%, bottom transparent.
  - Volume: a `HistogramSeries` on `priceScaleId: 'vol'`, each bar tinted by direction at 40%.
    Skip it when every volume is null or 0.
  - Markers through `createSeriesMarkers`:
    - news = `circle` aboveBar, size from impact, colour by direction (`--text-muted` when mixed).
  - `priceLines` and `baseline` use `createPriceLine`.
    - `baseline` is a dotted `--text-muted` line with no axis label.
  - Colours: resolve each token to `rgb()` through a hidden probe element's computed `color`
    (`color-mix(in srgb, var(--gain) 25%, transparent)` for alphas). Re-apply via `applyOptions`
    when a `MutationObserver` on `document.documentElement` attributes fires.
  - `subscribeCrosshairMove` passes the hovered bar (or `null` when `!param.time`) to `onCrosshair`.
  - `subscribeClick` maps `param.time` back to a date and calls `onPickDate`.
  - Unsubscribe and run `chart.remove()` on unmount.
  - Data updates call `setData` + `fitContent` without recreating the chart.
- [ ] **Step 4: Run, expect PASS**; also run `npm run build`.
- [ ] **Step 5: Commit** `feat(stock): PriceCanvas (lightweight-charts) and NewsStrip`

### Task 5: Rewrite `TradingChart`, wire callers, docs

**Files:**
- Modify: `frontend/src/components/stock/TradingChart.jsx` (full rewrite), `frontend/src/pages/Stock.jsx:110-113`
- Modify tests: `frontend/src/pages/Stock.test.js:51-54`; `IndexPage.test.js` only if the tag changes (it should not)
- Docs: `frontend/src/handbook/trading-and-money.md:332` area, `docs/wiki/frontend.md` (section + `verified_at`)

**Interfaces:**
- Consumes: Task 3 helpers; Task 4 components; `endpoints.intraday(symbol)`,
  `endpoints.marketIndexIntraday(t)` plus the `?days=` param (pass `{params: {days}}`); `usePrivacy`.
- Produces: `TradingChart` with unchanged props `{closes, trades, thesis, symbol, currency, initialRange, intradayUrl, newsUrl}`.
  - `closes` now accepts any `toBars` input.
  - `initialRange` defaults to `'1D'`.

- [ ] **Step 1: Update the failing source tests** (`Stock.test.js`)
  - Replace the `{...AXIS}`/`TOOLTIP_STYLE` assertions with:
    - `TradingChart.jsx` matches `/<PriceCanvas/`;
    - it matches `/hidePrices=\{hidden\}/`;
    - it keeps `/<span className="private">\{l\.amount\}/`.
  - `Stock.jsx` matches `/m\?\.bars/` and `/toBars\(/`, and does not match `/m\?\.closes/`.
- [ ] **Step 2: Run, expect FAIL** `cd frontend && node --test src/pages/Stock.test.js src/pages/IndexPage.test.js`
- [ ] **Step 3: Implement**
  - `TradingChart`:
    - Daily: `toBars(closes, {daily: true})`.
    - Intraday: fetched with `days` from `RANGES`. The loaded state is keyed `{symbol, days}` so a
      stale response never shows. Polls `INTRADAY_POLL_MS` while 1D or 1W.
    - The visible slice comes from `RANGES`.
    - `mode` state defaults to `'candle'` and is forced to `'area'` when `!ohlc`.
  - Layout, top to bottom:
    - **Readout**: price via the existing `fmt`; `rangeChange`, toned with `components/ui/tone`;
      on crosshair, date/time and O/H/L/C/Vol.
    - `PriceCanvas` in a `h-[320px] sm:h-[420px]` box with `role="img"` and an aria summary.
    - **Controls row**: chips from `visibleRanges(daily.length)`, then the Candles/Area toggle
      (disabled when `!ohlc`), then News with its day count (only when `allNews.length`).
    - `NewsStrip` for the picked date.
    - A compact legend, only for stop/target, with private amounts.
  - The old Recharts code, the `NewsMark` SVG and the long legend are deleted.
  - `baseline = prevClose(daily, sessionDate)` on 1D only. `sessionDate` = the first intraday bar's `date.slice(0, 10)`.
  - `Stock.jsx`: `closes` becomes the longer of `toBars(quick.data?.price_data, {daily: true}).bars`
    and `toBars(m?.bars, {daily: true}).bars`. Pass the raw longer array, so `TradingChart` normalises once.
  - Docs:
    - Update the handbook anchor text (lightweight-charts, OHLCV, ranges).
    - Update `docs/wiki/frontend.md` for the TradingChart / Stock / Index lines and the new
      `days` param, and bump `verified_at`.
    - Run `python3 docs/wiki/stale.py`.
- [ ] **Step 4: Verify** (run concurrently, in the background): `npm test`, `npm run build`, `cd backend && python -m pytest -q`. All green.
- [ ] **Step 5: Commit** `feat(chart): candle/area price chart with readout, ranges and news strip` (frontend + docs only).

### Task 6: Visual verification (no commit)

**Files:** scratchpad only: `shot_chart.py`, adapted from the prior session's Playwright harness
(`chrome-headless-shell` at `/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1248/...`).

- [ ] **Step 1:** `npm run build && npx vite preview --port 4174` (background).
- [ ] **Step 2:** Mock `**/api/v1/**`:
  - `/auth/me` returns the user;
  - `/market/index/^NSEI` returns 1300 synthetic OHLCV random-walk points;
  - `/market/index/^NSEI/intraday` returns 75 5m rows (`days=1`) or 125 15m rows (`days=5`);
  - quick-analyze `price_data` returns 252 candles;
  - `/mine/stock/INFY` returns bars plus 2 trades and a thesis;
  - `/news/symbol/INFY` returns 4 items over 3 dates;
  - everything else returns 404; `**/ws/**` is aborted.
  - Never use a real session token.
- [ ] **Step 3:** Capture `/stock/INFY` and `/index/%5ENSEI` at 390×844 and 1280×800, dark and light, in these states:
  - 1D;
  - 1Y candles;
  - area toggle;
  - a news dot clicked (strip open);
  - hide-amounts on (`localStorage neotrade_private=on`): no stop/target amounts on the axis.
  - Assert `scrollWidth <= innerWidth`.
- [ ] **Step 4:** Show the screenshots to the owner. Fix issues by looping back into Task 4/5 commits.
  Then ask the deploy-mode question and push.
