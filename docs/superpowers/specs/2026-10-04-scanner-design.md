# Scanner: real universe, two named setups, ATR stops

Date: 2026-10-04 · Status: design approved in chat ("Do it"), awaiting spec review

Sub-project 1 of 4 (scanner → order ticket → one decisions inbox → research search page).

## Problem

`backend/mcp_tools/stock_scanner.py` (Research → Scanner) is wrong in ways a trader acts on:

1. **Universe is 10 hardcoded scrips** (`HIGH_VOLATILITY_PICKS`: SUZLON, RVNL, IRCTC…). The page
   copy says "Sweeps the NIFTY universe".
2. **Blocks the event loop.** Sync `yf.Ticker().history()` per symbol, in series, inside an
   `async` route. Every other request and the WebSocket stall for the whole scan.
3. **Incoherent scoring.** "RSI < 40 oversold" (mean reversion) is added to "above SMA20" and "up
   3% this week" (momentum). `sma5 > sma20 * 0.98` fires for nearly every stock above its SMA20,
   so most rising stocks pass the 2-point bar on two correlated signals. SMA20 on `period="1mo"`
   is the mean of all data. Average volume includes today's partial bar. "Week ago" is
   `iloc[-5]` (4 bars back).
4. **Fake numbers.** Fixed +5% target / −3% stop on high-volatility names; "confidence" is
   `signals × 20`.
5. **Clicking a finding opens nothing.** It does `navigate('/', { state: { symbol } })`; `/` is
   now Today, which ignores `state`. Same bug in Watchlist, Portfolio (Practice → Book) and
   Market (index and symbol rows).

## Goal

A scan the trader can trust: their own universe, two named setups with fixed rules, stops and
targets from volatility, and a click that opens the stock.

## Non-goals

- No buy/sell button on findings yet (sub-project 2, order ticket).
- No scheduled scan or digest entry, no oversold-bounce or momentum-leader setups (declined).
- No score or verdict. Findings are leads, as today; proposals stay on the decisions page.
- No result caching. One batched download is fast enough for a manual button.

## Backend

### `backend/research/scanner.py` (new; replaces `backend/mcp_tools/stock_scanner.py`)

- `async fetch_daily(symbols: list[str]) -> dict[str, pd.DataFrame]`
  One `yf.download([f"{s}.NS" ...], period="1y", interval="1d", group_by="ticker",
  auto_adjust=True, threads=True, progress=False)` run via `asyncio.to_thread`. Returns
  bare symbol → OHLCV frame (columns `open high low close volume`, NaN rows dropped). A symbol
  with no rows is absent from the result.
- `find_setups(frames: dict[str, pd.DataFrame], now: datetime) -> ScanResult` — pure, no I/O.
  - **Completed bars only:** if the last bar's date is today (IST) and `now` is before 15:30
    IST, drop it.
  - A symbol with fewer than 200 bars after that is reported in `skipped` with reason
    `"under 200 bars"`; a requested symbol absent from `frames` is skipped with `"no data"`.
  - Indicators from `backend.components.quant.indicators.Indicators`: `rsi` (14), `sma`
    (20/50/200), `atr` (14).

### Setups (last completed bar = "today")

**Breakout** — all of:
- close > max(high) of the 20 bars before today;
- volume ≥ 1.5 × mean(volume) of the 20 bars before today;
- close > SMA50.
- Stop = close − 2 × ATR.

**Pullback in uptrend** — all of:
- close > SMA200 and SMA50 > SMA200;
- in the last 3 bars (today included), some low ≤ SMA20 + 1 × ATR or ≤ SMA50 + 1 × ATR, using
  each bar's own SMA value, and that low ≥ the SMA − 1 × ATR (touched, not broken through);
- 35 ≤ RSI ≤ 50 and RSI today > RSI yesterday;
- close > previous close.
- Stop = min(low of last 3 bars) − 0.5 × ATR.

A stock matching both is reported once, as **breakout**.

**For every finding:** target = close + 2 × (close − stop) (2R); `risk_pct` =
(close − stop) / close × 100; `change_pct` = today's close vs previous close; `return_3m` =
close vs close 63 bars back; `reasons` = the plain conditions that held, with numbers (e.g.
`"Closed ₹1,240 above 20-day high ₹1,228"`, `"Volume 2.1× 20-day average"`).
Findings sorted by `return_3m` descending (relative strength).

### Route: `backend/routers/scanner.py`

`GET /scanner` (auth required, mounted like today's router) → scans the user's
`PrefsStore(db.db).get(user.id)["universe"]`.

```json
{
  "scan_time": "2026-10-05T10:12:03+05:30",
  "as_of": "2026-10-03",
  "scanned": 48,
  "skipped": [{"symbol": "XYZ", "reason": "under 200 bars"}],
  "findings": [{
    "symbol": "ITC", "setup": "breakout", "close": 412.5, "change_pct": 2.1,
    "stop": 398.2, "target": 441.1, "risk_pct": 3.47, "return_3m": 8.4,
    "reasons": ["..."]
  }]
}
```

`as_of` = latest completed bar date across scanned frames. Empty universe → 200 with
`scanned: 0` and no findings. Download failure → 502 with a plain detail.

`server.py`: drop the `mcp_tools.stock_scanner` import/mount, mount the new router.
Delete `backend/mcp_tools/stock_scanner.py` and `/scanner/test`.

## Frontend

- `utils/api.js`: `scanner: '/scanner'`.
- `ScannerPage.jsx`:
  - Copy: "Sweeps your universe (N scrips) for breakouts and pullbacks in an uptrend, on
    completed daily bars." Meta: "As of <as_of> close · run <time>".
  - Filter chips: All · Breakout · Pullback (with counts).
  - Columns: Scrip (+ setup tag, reasons line) · Last · Change · Stop (risk %) · Target (2R) ·
    3M. Confidence column removed. Phone layout keeps the stacked card with the same fields.
  - Skipped scrips: one muted line, "Skipped N: no data / under 200 bars", expandable list.
- `navigate('/', { state })` → `navigate('/research', { state })` in `ScannerPage.jsx` (2),
  `Watchlist.jsx`, `Portfolio.jsx`, `Market.jsx` (2). `Dashboard.jsx` already reads
  `location.state` on `/research`.

## Testing

`backend/tests/test_scanner.py`, synthetic frames, no network:
- breakout fires; does not fire with volume at 1.49×; does not fire below SMA50;
- pullback fires; does not fire with RSI 51, with RSI falling, below SMA200, or when the low
  broke more than 1 ATR through the SMA;
- both match → one breakout finding;
- today's bar dropped before 15:30 IST and kept after;
- under 200 bars and missing symbol → `skipped`;
- stop/target/risk_pct math for each setup; sort by `return_3m`.

Router test: `fetch_daily` patched; response shape; empty universe; download error → 502.
Frontend: `npm run build` + lint (vitest alone does not type-check).
