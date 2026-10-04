# Stock detail: enough to decide, without AI

Date: 2026-10-04 · Status: design approved in chat, awaiting spec review

## Problem

Searching a stock (Research → Search, `AnalysisCard` Overview tab) shows a price, a chart,
eight particulars and four indicators. The backend already fetches about twenty more
fundamentals (`CompanyInfo`, `backend/components/shared/models.py:95`) and has trend and
support/resistance detectors (`backend/components/quant/`) that this page never uses. The
trader cannot tell at a glance whether a stock is cheap, healthy, trending, or near a level.

## Goal

One instant, AI-free page that serves both decisions the trader makes here:
**should I own it** (valuation, profitability, balance sheet) and **when to enter or exit**
(trend, levels, momentum, volume). A row of plain-fact flags sits on top.

## Non-goals

- No buy/sell verdict or score. Flags state facts (`PRODUCT.md`: nothing here is advice).
- No LLM call in this path; the AI Analysis tab is unchanged.
- No peer comparison (the peer lookup is a ~10 s LLM call, opt-in) and no sector-relative
  figures (no sector data source).
- No change to the strategy engine or `composite.py`.

## Backend: `quick_analysis` payload

`backend/research/quick.py` keeps one request, one 1-year daily history. `technical_analysis`
gains keys (existing `rsi`, `sma_50`, `sma_200`, `atr` unchanged). Every value is `None` when
the history is too short to compute it.

| Key | Meaning |
|---|---|
| `price` | last close |
| `ema_20` | 20-day EMA (`Indicators.ema`) |
| `macd`, `macd_signal` | last MACD line and signal (`Indicators.macd`, 12/26/9) |
| `bb_upper`, `bb_lower` | last Bollinger bands (`Indicators.bollinger_bands`, 20, 2σ) |
| `support`, `resistance` | nearest level below / above the last close (`SupportResistance.identify_levels` + `get_nearest_levels`) |
| `trend` | `"up"` / `"down"` / `"choppy"` from `TrendDetector.detect_trend` on `Indicators.calculate_all` (needs 200 bars, else `"choppy"`) |
| `returns` | `{"1w","1m","3m","6m","1y"}` % change of close over 5, 21, 63, 126 bars and the whole history |
| `volume_ratio` | last bar's volume ÷ mean of the 20 bars before it |
| `high_52w`, `low_52w` | max high / min low over the history |

New: `QuickAnalysis.flags: list[{code, label, tone}]`, `tone` ∈ `up`/`down`/`neutral`, built by
a pure function `stock_flags(technicals, company) -> list[dict]` in
`backend/research/flags.py`. Rules, in output order, each only when its inputs exist:

| Code | Condition | Label | Tone |
|---|---|---|---|
| `trend` | `trend` | "Uptrend" / "Downtrend" / "Sideways" | up / down / neutral |
| `vs_200` | price vs `sma_200` | "Above 200-day avg" / "Below 200-day avg" | up / down |
| `cross` | `sma_50` vs `sma_200` | "Golden cross" / "Death cross" | up / down |
| `rsi` | RSI > 70 / < 30 | "RSI 74 · overbought" / "RSI 26 · oversold" (rounded) | down / up |
| `near_high` | price ≥ 95% of 52-week high | "Near 52-week high" | neutral |
| `near_low` | price ≤ 105% of 52-week low | "Near 52-week low" | neutral |
| `volume` | `volume_ratio` ≥ 1.5 | "Volume 2.3× avg" (1 decimal) | neutral |
| `cash` | `total_debt` vs `total_cash` | "Debt > cash" / "Net cash" | down / up |
| `loss` | `trailing_eps` < 0 | "Loss-making" | down |
| `dividend` | `dividend_yield` > 0 | "Dividend 2.1%" | neutral |

52-week high/low come from `company_info` when present, else from `technical_analysis`.
`dividend_yield` is a fraction (0.021 → "2.1%").

## Frontend: Overview tab, top to bottom

`frontend/src/components/AnalysisCard.jsx` keeps its header and tabs; the header adds
industry beside sector and "prev close ₹X". The Overview becomes:

1. **Flags** (`analysis/StockFlags.jsx`) — chips, tone colours from existing tokens
   (`text-up` / `text-down` / ink). Hidden when empty.
2. **Price** — the existing `TradingChart`, then a returns strip (1W 1M 3M 6M 1Y, signed %,
   coloured; "—" when null).
3. **Trading levels** (`analysis/TradingLevels.jsx`) — replaces `TechnicalPanel` on this page:
   - Support / resistance with % distance from price.
   - Typical daily move: ATR in ₹ and as % of price.
   - 52-week range: a bar with the price's position, low and high printed.
   - Momentum: RSI with its reading, MACD above/below signal, Bollinger position
     (above upper / inside / below lower).
   - Averages: 20 EMA, 50, 200 with % distance from price.
4. **Fundamentals** (`analysis/Fundamentals.jsx`) — three groups:
   - *Valuation*: market cap, P/E, PEG, P/B, EPS (trailing / forward), dividend yield.
   - *Profitability*: ROE, ROA, operating margin, gross margin.
   - *Growth & balance sheet*: revenue, revenue growth, EBITDA, total debt, total cash,
     net cash (cash − debt), beta.
   - Missing values print "—"; a group with no values is not rendered.

`TechnicalPanel` stays in the codebase only if something else imports it; otherwise it is
deleted.

## Error handling

The payload already arrives whole or fails whole. Each new key may be `None`; every
component renders "—" for a `None` and hides a section with nothing in it. A support/
resistance or trend computation that throws is caught and leaves those keys `None`; the
rest of the snapshot still returns.

## Testing

- `backend/tests/test_stock_flags.py`: each rule on both sides of its threshold (RSI 70.1 vs
  69.9, price at 95% of high, volume ratio 1.5 vs 1.49, EPS −1, debt vs cash, dividend 0),
  and an empty input giving `[]`.
- `backend/tests/test_research_quick.py`: new keys present for 260 bars; `returns["1w"]`
  matches the hand value on the fixture; 30 bars give `sma_200`, `returns["6m"]`, `trend`
  `"choppy"` without raising; `flags` is a list on the payload.
- Frontend: `npm run build`, lint clean on touched files.
