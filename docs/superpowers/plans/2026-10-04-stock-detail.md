# Stock Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stock search shows fact flags, returns, trading levels and grouped fundamentals, instantly and without AI.

**Architecture:** `quick_analysis` computes the extra technicals from the 1-year history it already fetches, reusing `backend/components/quant/`; a pure `stock_flags` turns technicals + company info into fact chips. The frontend Overview tab is rebuilt from three new presentational components.

**Tech Stack:** FastAPI + pandas (backend), pytest; React 19 + Tailwind tokens (frontend).

**Spec:** `docs/superpowers/specs/2026-10-04-stock-detail-design.md`

## Global Constraints

- No LLM call anywhere in `backend/research/quick.py` or `flags.py` (existing test `test_quick_analysis_never_calls_the_llm` must stay green).
- Flags are facts, never buy/sell words. Labels and thresholds exactly as the spec's flag table.
- Every new technical value is `None` (never NaN or inf — JSON cannot carry them) when it cannot be computed.
- Backend tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest -q -p no:cacheprovider backend/tests/...`.
- Frontend: `npm --prefix frontend run build` plus `npx eslint` on touched files (repo-wide lint already has 3 unrelated errors).
- Deploy mode this session: **Direct** — commit subjects end `[skip ci]`; backend rebuilt by hand in `/home/ubuntu/deploys/NeoTrade`; Vercel builds the frontend on push.

## Review Focus

1. A close of `0` in old history must give that return `None`, not inf (bad ticks exist on yfinance). Test in Task 1.
2. All-zero volume must give `volume_ratio` `None`, not a ZeroDivisionError. Test in Task 1.
3. Company info with every optional field `None` (fresh listing, ETF) must give flags from technicals only, no KeyError/TypeError. Test in Task 2.
4. A history of 30 bars (recent IPO) must return without raising, with long-window values `None`. Test in Task 1.
5. A frontend `technical_analysis` from an old cached payload without the new keys must render "—", not crash. Task 3 manual check: components read every key with `?.`.

---

### Task 1: Extra technicals in `quick_analysis`

**Files:**
- Modify: `backend/research/quick.py` (`_compute_technicals`)
- Test: `backend/tests/test_research_quick.py`

**Interfaces:**
- Produces: `technical_analysis` keys `rsi, sma_50, sma_200, atr, price, ema_20, macd, macd_signal, bb_upper, bb_lower, support, resistance, trend, returns, volume_ratio, high_52w, low_52w`; `returns` = `{"1w","1m","3m","6m","1y"}` → float | None; `trend` ∈ `"up"|"down"|"choppy"`.

- [ ] **Step 1: Failing tests** (reuse the `wired` fixture; its closes are `2000 + i`, i = 0..259, volume 1,000,000):
  - `test_quick_analysis_returns_full_technicals`: every key above present; `price == 2259.0`; `returns["1w"] == pytest.approx((2259 / 2254 - 1) * 100)`; `returns["1y"] == pytest.approx((2259 / 2000 - 1) * 100)`; `trend == "up"`; `volume_ratio == pytest.approx(1.0)`; `high_52w == 2264.0`; `low_52w == 1995.0`.
  - `test_short_history_leaves_long_values_none`: history = first 30 candles → `sma_200 is None`, `returns["6m"] is None`, `trend == "choppy"`, `returns["1w"]` not None.
  - `test_zero_close_and_zero_volume_give_none`: 260 candles with `close=0` at index 0 and every `volume=0` → `returns["1y"] is None`, `volume_ratio is None`.
- [ ] **Step 2:** run → FAIL (missing keys).
- [ ] **Step 3:** Implement in `_compute_technicals(candles) -> dict`. Returns over 5/21/63/126 bars and the whole history; a return is `None` when the history is shorter than the window + 1 or the base close is `0`. `volume_ratio` = last volume ÷ mean of the 20 bars before it; `None` when fewer than 21 bars or that mean is 0. Support/resistance: `SupportResistance.identify_levels(df)` then `get_nearest_levels(price, levels)`. Trend: `TrendDetector.detect_trend(Indicators.calculate_all(df)).value`. Wrap levels and trend each in `try/except Exception` → `None` / `"choppy"` with a `logger.warning`. Empty candles still return `{}`.
- [ ] **Step 4:** `backend/tests/test_research_quick.py` → all PASS.
- [ ] **Step 5: Commit** `feat(research): returns, levels, trend, momentum and volume in the stock snapshot [skip ci]`.

### Task 2: `stock_flags`

**Files:**
- Create: `backend/research/flags.py`
- Modify: `backend/research/quick.py` (`QuickAnalysis.flags: list[dict] = []`, filled by `stock_flags`)
- Test: `backend/tests/test_stock_flags.py`

**Interfaces:**
- Consumes: Task 1's `technical_analysis` dict.
- Produces: `stock_flags(technicals: dict, company: dict) -> list[dict]`, each `{"code": str, "label": str, "tone": "up"|"down"|"neutral"}`, in the spec's table order. `QuickAnalysis.flags`.

- [ ] **Step 1: Failing tests** (one per rule; assert on `code`, `label`, `tone` of the matching flag):
  - `trend`: `"up"` → `("Uptrend","up")`; `"choppy"` → `("Sideways","neutral")`.
  - `vs_200`: price 110 / sma_200 100 → `"Above 200-day avg"`, up.
  - `cross`: sma_50 90 / sma_200 100 → `"Death cross"`, down.
  - `rsi`: 70.1 → `"RSI 70 · overbought"`, down; 69.9 → no `rsi` flag; 25.6 → `"RSI 26 · oversold"`, up.
  - `near_high`: price 95, high 100 → present; price 94.9 → absent.
  - `near_low`: price 105, low 100 → present; 105.1 → absent.
  - `volume`: 1.5 → `"Volume 1.5× avg"`; 1.49 → absent.
  - `cash`: debt 10 / cash 5 → `"Debt > cash"`, down; debt 5 / cash 10 → `"Net cash"`, up.
  - `loss`: trailing_eps -1 → `"Loss-making"`, down.
  - `dividend`: 0.021 → `"Dividend 2.1%"`; 0 → absent.
  - 52-week high falls back to `technicals["high_52w"]` when `company["week_52_high"]` is None.
  - `test_empty_inputs`: `stock_flags({}, {}) == []`.
  - `test_company_all_none`: technicals with trend "up", company of only None values → only technical flags, no exception.
  - In `test_research_quick.py`: `test_quick_analysis_carries_flags` → `result.flags` is a non-empty list containing code `"trend"`.
- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3:** Implement `stock_flags`; wire `flags=stock_flags(technicals, company_info_dict)` in `quick_analysis`.
- [ ] **Step 4:** both test files PASS; full backend suite PASS.
- [ ] **Step 5: Commit** `feat(research): fact flags on the stock snapshot [skip ci]`.

### Task 3: Overview tab rebuilt

**Files:**
- Create: `frontend/src/components/analysis/StockFlags.jsx` (`({ flags })`)
- Create: `frontend/src/components/analysis/TradingLevels.jsx` (`({ t, currency })`, `t` = `technical_analysis`)
- Create: `frontend/src/components/analysis/Fundamentals.jsx` (`({ company, currency })`)
- Modify: `frontend/src/components/AnalysisCard.jsx` (header: industry + prev close; Overview order: flags, price sheet with returns strip, levels, fundamentals)
- Delete: `frontend/src/components/analysis/TechnicalPanel.jsx` (only `AnalysisCard` imports it)

**Interfaces:**
- Consumes: Task 1 keys, Task 2 `quick.flags`.

- [ ] **Step 1:** `StockFlags`: chips; tone → `text-up` / `text-down` / `text-[var(--ink)]`, bordered with `--rule-strong`; renders nothing for an empty list.
- [ ] **Step 2:** Returns strip under `TradingChart` inside the Price sheet: five cells 1W 1M 3M 6M 1Y, `formatSignedPercent`, `text-up`/`text-down`, "—" for null.
- [ ] **Step 3:** `TradingLevels` sheet "Trading levels", rows as the spec §Frontend 3: support/resistance with `% from price`; "Typical daily move" ATR ₹ and % of price; 52-week range bar (position = (price−low)/(high−low), clamped 0–100); momentum (RSI value + reading overbought/oversold/neutral; MACD "above signal"/"below signal"; Bollinger "above upper band"/"inside bands"/"below lower band"); averages 20 EMA / 50 / 200 with % from price. Every key read with `?.`; null → "—".
- [ ] **Step 4:** `Fundamentals` sheet with three groups exactly as the spec lists; fractions (ROE, ROA, margins, revenue growth, dividend yield) ×100 via `formatPercent`; money via `formatCompactNumber` prefixed by currency symbol through `formatCurrency` where it is a price, compact otherwise; net cash = cash − debt when both exist; a group with every value null is not rendered.
- [ ] **Step 5:** `npm --prefix frontend run build` → built; `npx eslint` on the five touched files → clean.
- [ ] **Step 6: Commit** `feat(research): stock page -- flags, returns, trading levels, grouped fundamentals [skip ci]`; push; rebuild backend in `/home/ubuntu/deploys/NeoTrade` (`git pull --ff-only && docker compose build backend && docker compose up -d backend`); `curl http://127.0.0.1:8000/` → 200; Vercel newest production deploy Ready.
