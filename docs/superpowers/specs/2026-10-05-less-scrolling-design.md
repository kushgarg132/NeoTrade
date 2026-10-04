# Less scrolling on phone

Date: 2026-10-05 · Status: design approved in chat ("Yes, write the spec"), awaiting spec review

## Problem

Measured on the live app at 390 × 844 with the owner's data (2026-10-04; one screen = 844 px):

| Page | Height | Screens | Tallest part |
|---|---|---|---|
| Decisions | 5485 | 6.5 | 13 proposal cards × 371 px |
| Research → stock (ITC) | 3917 | 4.6 | Fundamentals 1703, Trading levels 896 |
| Practice → Settings | 3401 | 4.0 | Strategies 1626 |
| Practice → Overview | 2709 | 3.2 | Is it working 1131 |
| Settings → Safety | 2379 | 2.8 | Guardrails 1582 |
| Practice → Book | 2335 | 2.8 | Executions 1607 |
| Research (front) | 2205 | 2.6 | Indices 842, Movers 581 |
| Mine → Holdings | 1720 | 2.0 | Action plan 1176 |

Four patterns cause it:
- **A. Stacked setting rows.** `components/settings/Fields.jsx` `Row`: label, full hint, then the
  control wraps below — ~110 px per setting.
- **B. One paragraph per strategy.** `EngineSettings.jsx` (Strategies) and
  `StrategyReadiness.jsx` (Is it working) repeat the same go-live sentence for 9 strategies.
- **C. Unbounded lists.** Executions (25 fills), the Action plan Markdown, full proposal cards.
- **D. Stacked figures.** `Statement` on phone (`index.css` 232-282) turns each row into a record
  with a caption per value — ~66 px per figure in 2–3 column tables; `TradingLevels` does the
  same by hand.

## Goal

Each page above fits in **≤ 1.5 phone screens** with the same data, except the stock page
(**≤ 2.2**, the chart stays). Desktop gets the same compactness; no information is removed, only
folded.

## Non-goals

- No content or data changes, no new endpoints.
- No redesign of pages already ≤ 1.5 screens (Today, Scanner, Watchlist, Options, Accounts).
- Desktop layouts beyond what the shared components change.

## Design

### A. Compact setting row (`components/settings/Fields.jsx` `Row`)

- One line: label (left, may wrap to 2 lines) and control (right, `shrink-0`), no `flex-wrap`.
- Hint under the label, clamped to **one line** (`line-clamp-1`); tapping the hint toggles the
  full text (`aria-expanded`). Hints of ≤ 60 characters render unclamped.
- Vertical padding `py-2` (was `py-3`).
- `NumberField` width `w-24` (was `w-36`).
- Applies everywhere `Row` is used: Settings (Guardrails, Portfolio review, AI), Profile,
  EngineSettings (Daily auto-run, Engine mandate, Daily scan), StrategyReadiness.

### B. Strategy table (`EngineSettings.jsx` Strategies, `StrategyReadiness.jsx`)

- The go-live rule is printed **once** under the sheet title: "To go live a strategy needs a
  passing year's backtest, 20 paper days, 30 trades, a net profit after charges, profit factor
  1.3 and no fall deeper than 5% of your account."
- Each strategy is **one row**: name · short status · control.
  - Short status from the data already shown: `backtest ✓/✗/–` · `{days}/20 days` ·
    `{trades}/30 trades` (or `ready` when all pass).
  - Control: the existing Paper/Live chip (EngineSettings); none in StrategyReadiness.
- Tapping a row expands it in place to today's full text and the "Run a year's backtest" link.
  One row open at a time.

### C. Capped and collapsible lists

- **Executions** (`pages/Portfolio.jsx`): latest **10**, then `Show all {n}` toggles to the
  existing 25.
- **Action plan** (`pages/MyPortfolio.jsx`): the Markdown is split on its `###`/`**…**` group
  headings (Improve the mix / Sell or trim / Add …) into collapsible groups; the first group open,
  each heading shows its bullet count. If the Markdown has no recognised headings it renders as
  today but clamped to 12 lines with `Show all`.
- **Decisions** (`SuggestionRecord.jsx`): collapsed card = symbol · side × qty · entry / stop /
  target on one line · score · Decline / Approve on paper / Approve with real money. Thesis,
  reasons and option terms go behind the existing `Why` toggle (closed by default). Target
  ≤ 170 px per pending card.

### D. One-line figures

- `Statement` gets an `inline` prop. With it, on phone each row stays one line: first cell left,
  the other cells right-aligned on the same line, no per-cell caption (the header row stays
  visually hidden for screen readers). Without the prop, behaviour is unchanged.
- Use `inline` on: Market Indices and Movers, Fundamentals (2 columns), and any other
  ≤ 3-column `Statement` the plan finds.
- **Fundamentals**: inline rows inside a `grid sm:grid-cols-2` per group, so phone shows one
  compact line per figure.
- **Trading levels** (`TradingLevels.jsx`): each level one line — name · value · note.
- **Indices**: the 4 Indian indices shown; the world indices behind `World ›` (toggle).

## Verification

Re-run the measurement script (Playwright, 390 × 844, live data, short-lived token for the owner)
after deploy and report a before/after table plus screenshots for every page above. Each must
meet the Goal; any that misses is reported with its tallest section.

Frontend: `npm run build` + lint on changed files.
