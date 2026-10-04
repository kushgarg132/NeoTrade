# Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 10-scrip, event-loop-blocking bullish scanner with a scan of the user's universe for two named setups (breakout, pullback in uptrend) with ATR stops and 2R targets, and make every "open this stock" click land on Research.

**Architecture:** `backend/research/scanner.py` holds a pure `find_setups(frames, symbols, now)` plus an I/O shell `fetch_daily(symbols)` (one batched `yf.download` in a thread). `backend/routers/scanner.py` serves `GET /scanner` over the user's `prefs["universe"]`. `ScannerPage.jsx` renders the new shape; five `navigate('/', {state})` calls move to `/research`.

**Tech Stack:** FastAPI, pandas, yfinance, pytest + FastAPI TestClient; React 19 + Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-scanner-design.md`

## Global Constraints

- Completed bars only: drop the last bar when its date is today (IST) and `now` < 15:30 IST.
- Under 200 completed bars → skipped `"under 200 bars"`; requested symbol absent from frames → skipped `"no data"`.
- Indicators come from `backend.components.quant.indicators.Indicators` (`rsi` 14 Wilder, `sma` 20/50/200, `atr` 14). No new indicator code.
- Target = close + 2 × (close − stop). `risk_pct` = (close − stop) / close × 100. `return_3m` = close vs close 63 bars back, in %. Sort findings by `return_3m` descending.
- A stock matching both setups is one finding, `setup="breakout"`.
- No score, no "confidence" field anywhere. Findings are leads, not advice (`PRODUCT.md`).
- No buy/sell button on findings (sub-project 2).
- Frontend check is `npm run build` + `npm run lint`, not vitest alone.

## Review Focus

1. **NaN in the latest bar** (yfinance sometimes returns a NaN close for a halted scrip) → that row is dropped before indicators, never a NaN in JSON. Test in Task 1.
2. **A scrip whose download comes back empty while others succeed** → listed in `skipped` as `"no data"`, scan still returns 200. Test in Task 1 (`find_setups`) and Task 2 (router).
3. **Single-symbol universe** → `yf.download` with one ticker and `group_by="ticker"` still yields a per-ticker frame; `fetch_daily` must not assume a MultiIndex. Test in Task 2.
4. **Scan run at 15:29 vs 15:31 IST on a trading day** → partial bar dropped vs kept. Test in Task 1.
5. **Clicking a finding / watchlist row / book row / market row** → Research opens that stock. Checked by build + manual click in Task 3.

---

### Task 1: Pure setup detection

**Files:**
- Create: `backend/research/scanner.py`
- Test: `backend/tests/test_scanner.py`, frame builders in `backend/tests/scanner_frames.py` (Task 2 reuses them)

**Interfaces:**
- Produces (all in `backend/research/scanner.py`):
  - `class Finding(BaseModel)`: `symbol: str, setup: Literal["breakout", "pullback"], close: float, change_pct: float, stop: float, target: float, risk_pct: float, return_3m: float, reasons: list[str]` (floats rounded to 2 dp).
  - `class Skipped(BaseModel)`: `symbol: str, reason: Literal["no data", "under 200 bars"]`.
  - `class ScanResult(BaseModel)`: `as_of: Optional[date], scanned: int, skipped: list[Skipped], findings: list[Finding]`.
  - `def find_setups(frames: dict[str, pd.DataFrame], symbols: list[str], now: datetime) -> ScanResult` — `frames` keys are bare symbols, each frame has a `DatetimeIndex` and columns `open high low close volume`. `scanned` = `len(symbols)`. `as_of` = max last completed bar date across evaluated frames, `None` if none.

- [ ] **Step 1: Write the failing tests**

Test helper `_frame(close, high=None, low=None, volume=None, end=date(2026, 10, 2))` builds a business-day `DatetimeIndex` ending at `end`; default `high = close + 1`, `low = close - 1`, `volume = 1000`. Each fixture builder asserts its own preconditions with `Indicators` before returning (e.g. the pullback fixture asserts `35 <= rsi[-1] <= 50` and `rsi[-1] > rsi[-2]`), so a fixture that drifts fails loudly instead of testing nothing. `NOW = datetime(2026, 10, 5, 10, 0, tzinfo=IST)` (a later day, so no bar is dropped) unless the test says otherwise.

```python
def test_breakout_fires():                       # 250-bar gentle uptrend, last close = prior-20 max high + 2, volume 2000
    f = find_setups({"AAA": breakout_frame()}, ["AAA"], NOW).findings
    assert [x.setup for x in f] == ["breakout"]
    assert f[0].stop == round(close - 2 * atr, 2) and f[0].target == round(close + 2 * (close - f[0].stop), 2)
    assert any("20-day high" in r for r in f[0].reasons) and any("20-day average" in r for r in f[0].reasons)

def test_breakout_needs_1_5x_volume():           # same frame, last volume = 1.49 × prior-20 mean
    assert find_setups({"AAA": breakout_frame(vol_mult=1.49)}, ["AAA"], NOW).findings == []

def test_breakout_needs_close_above_sma50():     # downtrend frame whose last bar still clears the prior-20 high
    assert find_setups({"AAA": breakout_below_sma50_frame()}, ["AAA"], NOW).findings == []

def test_pullback_fires():                       # uptrend > SMA200, SMA50 > SMA200, 3-bar dip to SMA20, RSI 35–50 rising, close > prev close
    f = find_setups({"BBB": pullback_frame()}, ["BBB"], NOW).findings
    assert [x.setup for x in f] == ["pullback"]
    assert f[0].stop == round(min(last3_lows) - 0.5 * atr, 2)

@pytest.mark.parametrize("variant", ["rsi_51", "rsi_falling", "below_sma200", "broke_through_sma", "close_below_prev"])
def test_pullback_rejects(variant):
    assert find_setups({"BBB": pullback_frame(variant)}, ["BBB"], NOW).findings == []

def test_both_setups_reported_once_as_breakout():
    f = find_setups({"CCC": both_frame()}, ["CCC"], NOW).findings
    assert [(x.symbol, x.setup) for x in f] == [("CCC", "breakout")]

@pytest.mark.parametrize("hhmm,as_of", [((15, 29), date(2026, 10, 2)), ((15, 31), date(2026, 10, 5))])
def test_partial_bar_dropped_before_close(hhmm, as_of):   # flat 250-bar frame ending Mon 2026-10-05
    now = datetime(2026, 10, 5, *hhmm, tzinfo=IST)
    assert find_setups({"AAA": _frame([100.0] * 250, end=date(2026, 10, 5))}, ["AAA"], now).as_of == as_of

def test_skipped_reasons():                      # "SHORT" has 150 bars, "GONE" absent from frames
    r = find_setups({"SHORT": _frame([100.0] * 150)}, ["SHORT", "GONE"], NOW)
    assert {(s.symbol, s.reason) for s in r.skipped} == {("SHORT", "under 200 bars"), ("GONE", "no data")}
    assert r.scanned == 2 and r.findings == []

def test_nan_last_row_is_dropped():              # breakout frame + one trailing all-NaN row → still one finding, json has no NaN
    r = find_setups({"AAA": with_nan_tail(breakout_frame())}, ["AAA"], NOW)
    assert len(r.findings) == 1 and "NaN" not in r.model_dump_json()

def test_sorted_by_return_3m():                  # two breakout frames with different 63-bar returns
    assert [x.symbol for x in find_setups(two, ["LOW", "HIGH"], NOW).findings] == ["HIGH", "LOW"]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && python -m pytest tests/test_scanner.py -q`
Expected: FAIL, `ModuleNotFoundError: backend.research.scanner`.

- [ ] **Step 3: Implement `find_setups` and the models in `backend/research/scanner.py`**

Per symbol: `dropna(subset=["close"])`; drop the last row if its date == `now.astimezone(IST).date()` and `now` IST time < 15:30 (`IST` from `backend.engine.session`); skip if < 200 rows; compute indicator series once; evaluate breakout first, then pullback only if breakout did not fire. Rules, stop formulas and the pullback "touched, not broken" band (`SMA − ATR ≤ low ≤ SMA + ATR`, per bar's own SMA, last 3 bars) exactly as the spec's Setups section. Reasons are plain sentences with numbers, formatted `₹{x:,.2f}` / `{x:.1f}×`. Module docstring states the two setups and that this is pure (no I/O).

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd backend && python -m pytest tests/test_scanner.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/research/scanner.py backend/tests/test_scanner.py
git commit -m "feat(scanner): breakout and pullback setups on completed bars, ATR stops, 2R targets"
```

---

### Task 2: Fetch, route, retire the old scanner

**Files:**
- Modify: `backend/research/scanner.py` (add `fetch_daily`)
- Create: `backend/routers/scanner.py`
- Modify: `backend/server.py:46,158` (swap import and mount)
- Delete: `backend/mcp_tools/stock_scanner.py`
- Test: `backend/tests/test_scanner_router.py`

**Interfaces:**
- Consumes: `find_setups`, `ScanResult` from Task 1.
- Produces:
  - `async def fetch_daily(symbols: list[str]) -> dict[str, pd.DataFrame]` in `backend/research/scanner.py` — bare symbol keys, lowercase OHLCV columns, symbols with no rows omitted.
  - `GET /scanner` → `ScanResponse(ScanResult)` with extra `scan_time: datetime` (IST, aware). `backend/routers/scanner.py`: `router = APIRouter(tags=["Scanner"])`, dependency `async def get_universe(user: User = Depends(get_current_user)) -> list[str]` returning `(await PrefsStore(db.db).get(user.id))["universe"]`.

- [ ] **Step 1: Write the failing tests**

Client fixture: `FastAPI()` + `include_router(scanner_router.router)`, override `get_current_user` (same `_USER` shape as `test_suggestions_router.py`) and `get_universe`; `monkeypatch.setattr(scanner_router, "fetch_daily", fake)`.

```python
def test_scan_returns_findings_and_skipped(client_with(universe=["AAA", "GONE"], frames={"AAA": breakout_frame()})):
    body = client.get("/scanner").json()
    assert body["scanned"] == 2 and body["findings"][0]["setup"] == "breakout"
    assert body["skipped"] == [{"symbol": "GONE", "reason": "no data"}] and "scan_time" in body and "confidence" not in body["findings"][0]

def test_empty_universe():                       # universe [], fake fetch_daily records calls
    body = client.get("/scanner").json()
    assert (body["scanned"], body["findings"], calls) == (0, [], [])

def test_download_failure_is_502():              # fake fetch_daily raises RuntimeError
    r = client.get("/scanner")
    assert r.status_code == 502 and "data provider" in r.json()["detail"]

async def test_fetch_daily_single_symbol(monkeypatch):   # yf.download patched to return a flat (non-MultiIndex) frame
    frames = await scanner.fetch_daily(["ITC"])
    assert list(frames) == ["ITC"] and {"open", "high", "low", "close", "volume"} <= set(frames["ITC"].columns)

async def test_fetch_daily_drops_empty_symbol(monkeypatch):  # MultiIndex result where "GONE.NS" is all NaN
    assert set(await scanner.fetch_daily(["ITC", "GONE"])) == {"ITC"}
```

Import `breakout_frame` from `backend/tests/scanner_frames.py` (Task 1).

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && python -m pytest tests/test_scanner_router.py -q`
Expected: FAIL, `ImportError: backend.routers.scanner`.

- [ ] **Step 3: Implement `fetch_daily`, the router, and the server swap**

`fetch_daily`: one `yf.download([f"{s}.NS" for s in symbols], period="1y", interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)` inside `asyncio.to_thread`; handle both MultiIndex and flat column results; lowercase columns; drop all-NaN frames. Router: empty universe returns without calling `fetch_daily`; any exception from `fetch_daily` → `HTTPException(502, "The market data provider did not respond. Try again in a minute.")` and `logger.exception`. `server.py`: replace `from backend.mcp_tools import stock_scanner` / its mount with `from backend.routers import scanner` mounted identically (`prefix=settings.API_PREFIX, tags=["Scanner"], dependencies=[Depends(get_current_user)]`). `git rm backend/mcp_tools/stock_scanner.py`.

- [ ] **Step 4: Run tests, verify they pass, then the full suite**

Run: `cd backend && python -m pytest tests/test_scanner.py tests/test_scanner_router.py -q && python -m pytest -q`
Expected: all PASS; no test imports `stock_scanner`.

- [ ] **Step 5: Commit**

```bash
git add backend/research/scanner.py backend/routers/scanner.py backend/server.py backend/tests/
git commit -m "feat(scanner): GET /scanner over the user's universe; retire the 10-scrip bullish scan"
```

---

### Task 3: Scanner page and Research links

**Files:**
- Modify: `frontend/src/utils/api.js:124`
- Modify: `frontend/src/pages/ScannerPage.jsx`
- Modify: `frontend/src/pages/Watchlist.jsx:64`, `frontend/src/pages/Portfolio.jsx:187`, `frontend/src/components/dashboard/Market.jsx:100,125`

**Interfaces:**
- Consumes: `GET /scanner` response from Task 2 (`scan_time, as_of, scanned, skipped[], findings[]`).

- [ ] **Step 1: Point the endpoint and fix the links**

`endpoints.scanner = '/scanner'`. Every `navigate('/', { state: ... })` in the four files becomes `navigate('/research', { state: ... })`; `grep -rn "navigate('/', { state" frontend/src` returns nothing afterwards.

- [ ] **Step 2: Rebuild `ScannerPage.jsx` on the new shape**

Keep the existing `Sheet / Statement / Row / Cell / Field / Scrip / Badge` building blocks and the phone-cards + desktop-table split. Changes, copy exact:
- Intro: `Sweeps your universe ({scanned} scrips) for breakouts and pullbacks in an uptrend, on completed daily bars. Findings are leads to enquire on — sized proposals with a stop arrive on the decisions page instead.` Before the first run, `({scanned} scrips)` is omitted.
- Sheet meta: `As of {as_of formatted en-IN} close · run {scan_time time}`.
- Filter chips above the findings: `All · Breakout · Pullback`, each with its count; selected chip filters rows (local state, default All).
- Setup tag next to the scrip (`Badge`: "Breakout" / "Pullback"); reasons line under it as today.
- Columns: Scrip · Last · Change · Stop (`{stop} · {risk_pct}%` below) · Target (2R) · 3M. Confidence column removed. Phone card fields: Last, Stop, Target, 3M.
- Skipped: when `skipped.length`, one muted line `Skipped {n}: no data or under 200 bars` that toggles a list of `symbol — reason`.
- Empty findings copy: `Nothing set up` / `No scrip in your universe is breaking out or pulling back in an uptrend right now.`

- [ ] **Step 3: Build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: build succeeds, lint 0 errors.

- [ ] **Step 4: Manual check against the local backend**

Run the backend, open Research → Scanner, Run scan: findings render with setup tags and chips filter; clicking a finding opens that stock on Research; a Watchlist row and a Market row do the same.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(scanner): setup tags, filters, ATR stop and 2R target; stock links open Research"
```
