# Price chart redesign (Stock + Index pages)

Date: 2026-10-31. Status: design approved in chat, spec awaiting review.

## Problem

`frontend/src/components/stock/TradingChart.jsx` (Recharts) drives the price chart on `/stock/:symbol`,
`/index/:ticker` and `AiTrade`. Owner feedback: it looks flat and cheap, has no hover readout, is the
wrong chart type (close-only line, no candles or volume), the controls and layout are clumsy, and the
news view and markers are bad.

## Decisions

- Engine: **TradingView `lightweight-charts`** (Apache-2.0, ~45 KB gz, canvas). Chosen over hand-built
  Recharts candles (no pan/zoom, low visual ceiling) and ECharts (~300 KB+, second chart style).
  Recharts stays for every other chart in the app.
- `TradingChart` keeps its props (`closes`, `trades`, `thesis`, `symbol`, `currency`, `initialRange`,
  `intradayUrl`, `newsUrl`), so callers barely change.

## Layout and interaction

- **Header readout** above the chart: big price, plus change and % since the range start, toned
  gain/loss. While the crosshair is active it shows that bar's date/time, O/H/L/C and volume instead.
  On release it returns to the latest value. Replaces the Recharts tooltip.
- **Body:** candles by default, with a toggle to area (line with a soft gradient fill). Volume is a
  faint histogram in the bottom ~20%, tinted by candle direction. Right price scale with a last-price
  label; minimal grid. Height 320 px on phone, 420 px on desktop.
- **Gestures:** drag pans, pinch or wheel zooms, double-tap resets (fit content).
- **Controls:** one compact segmented pill row under the chart: `1D 1W 1M 6M 1Y 5Y`. The candle/area
  toggle and the News toggle sit at its right end. A chip whose range has no more data than the
  next-shorter chip is hidden.
- **Trades:** arrow markers, `B` below the bar and `S` above it. Letter and shape carry the meaning,
  never colour alone.
- **Thesis:** stop and target as dashed price lines with axis labels ("Target ₹1,240", "Stop ₹1,080").
  Daily ranges only, as today.
- **News:** small dot on the day's bar, coloured by direction (gain / loss / muted for mixed) and
  sized by impact. Tapping a dot, or crosshairing that day, opens a horizontally scrollable headline
  strip under the chart. Each compact card shows direction, title, source and time, and links via
  `NewsLink`. This replaces today's vertical list. The old marker legend is dropped. Indices have no
  news (`newsUrl={null}`), as today.
- **1D:** 5-minute candles, polled every 60 s, with a dotted previous-close line.
- **Theme:** colours are read from CSS tokens (`--gain`, `--loss`, `--text-muted`, `--border`,
  `--surface`, `--accent`) via `getComputedStyle`. They are re-applied when the theme changes, so dark
  and light both work.
- **Accessibility:** the chart container keeps `role="img"` with a text summary (last price, range
  change, trade count, news days). Controls are real buttons with `aria-pressed`, min height 44 px.

## Data

Normalised chart row: `{date, open, high, low, close, volume}`. `date` is `YYYY-MM-DD` for daily rows
and an ISO timestamp for intraday rows; it is mapped to lightweight-charts `time` at `setData`.
`toBars(rows)` in `frontend/src/utils/stock.js` accepts:

- full candles (`PriceCandle`: `timestamp`, OHLCV);
- index intraday rows (`t`, OHLCV);
- the old close-only shape `{date, close}`. Close-only data renders as area, with the candle toggle
  disabled and no volume. `AiTrade` keeps working unchanged.

Existing `newsMarkers` / `tradeMarkers` are reused; they key on `date`.

### Backend (all additive)

- `backend/routers/market_data.py`
  - `_fetch_index_detail_sync`: each `points` row gains `open`, `high`, `low`, `volume`. `date` and
    `close` are unchanged, so the hero figures are unaffected.
  - `/market/index/{ticker}/intraday`: rows gain `open`, `high`, `low`, `volume`. A new query param
    `days` (1 or 5, default 1) selects 1d/5m or 5d/15m. The cache is keyed on `(ticker, days)`.
    Other values return 422.
- `backend/routers/agents.py` `/agents/intraday/{symbol}`: same `days` param (1 → 1d/5m, 5 → 5d/15m).
- `backend/mine/stock.py`: `closes` is replaced by `bars` (OHLCV from the same `daily_bars` frame).
  The only reader is `frontend/src/pages/Stock.jsx`, which changes in the same release.

### Frontend sources

- `Stock.jsx` passes `quick.price_data` as full candles (not stripped to closes) and reads `m.bars`;
  the longer series still wins.
- `IndexPage.jsx` passes `data.points` as before (now OHLCV).
- 1W uses the intraday feed with `days=5`; 1M/6M/1Y/5Y slice the daily series (22/126/252/1260 bars).
- Previous-close line on 1D: the close of the last daily bar dated before the session date. It is
  skipped if no such bar exists.

### Known limit

Both stock sources currently hold about 1 year (`quick` asks for `period="1y"`, `mine` reads 365
days). On the stock page 5Y therefore shows what exists, and the chip is hidden when it would equal
1Y. Real 5Y for stocks is a separate change.

## Failure handling

- Empty or failed price feed: the existing "No price history for this range." state (and "Loading…"
  while 1D/1W load).
- News fetch failure: no markers; the chart works.
- Missing volume: no histogram.
- Polling stops on unmount and when the range leaves 1D/1W.

## Testing

- vitest:
  - `toBars` (candle passthrough, `t`/`timestamp`/`date` keys, close-only fallback);
  - range slicing and chip hiding;
  - previous-close pick.
- `Stock.test` / `IndexPage.test` mock `lightweight-charts` (jsdom has no canvas).
- `npm run build` runs as a build check alongside vitest.
- pytest:
  - index `points` carry OHLCV;
  - intraday `days=5` uses 5d/15m with its own cache entry, and a bad `days` returns 422;
  - stock intraday `days` maps the same way;
  - `mine.stock` returns `bars`.
- Visual check before push:
  - Playwright harness with a mocked API and synthetic OHLCV (no real session token);
  - Stock + Index pages, at 390 px and 1280 px, dark and light;
  - states: 1D, 1Y candles, area mode, trade markers, news strip open.

## Docs

The same commits update:

- the `TradingChart` anchor in `frontend/src/handbook/trading-and-money.md`;
- the matching `docs/wiki/` page with its `verified_at`;
- `DESIGN.md`, only if a new chart token is added.

## Rollout

Two commits: backend first (additive; the old frontend ignores the new fields), then frontend.
Deploy mode (direct vs CI/CD) is asked once before the first push.

## Out of scope

- Real 5Y history for stocks.
- Indicators (SMA/EMA overlays).
- Comparing against an index.
- Moving other Recharts charts to lightweight-charts.
