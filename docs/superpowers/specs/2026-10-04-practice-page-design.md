# Practice page: say what it is, what it's doing, and whether it works

Date: 2026-10-04 · Status: approved in chat, awaiting spec review · Frontend only

## Problem

`/ai/practice` does not tell the trader what it is or what it is doing.

- It sits under **AI**, but it is the **strategy engine's** paper book, not the AI autopilot
  (the autopilot's own paper book is shown on AI → Overview). Nothing on the page says so.
- The Overview opens on the Scorecard's statistics (profit factor, drawdown, vs NIFTY), then
  P&L, then a trade list. Whether anything is running, and what runs next, is only on the
  Engine tab.
- Engine and Holdings both list open paper positions.
- Two tab rows stack: the AI tabs, then five dashed paper tabs.

## Goal

Opening Practice answers three questions, in this order:

1. **What is this?** The strategy engine trading practice money. Not the autopilot.
2. **What is it doing now?** Running or idle, auto-run on or off, today's paper P&L, open
   positions, what waits for a decision, and whether any strategy is armed for real money.
3. **Is it working?** Per strategy: how far it is from earning real money, and then the full
   track record.

Decided in chat: Practice stays under AI at `/ai/practice`; the page explains itself rather
than moving.

## Non-goals

- No backend change. Every figure comes from an endpoint the pages already call.
- No change to the AI tabs, the autopilot pages, Decisions, or Settings content.
- The dashed paper stamp (`PaperShell`) stays: a paper figure must never read as broker money.

## Design

### Sub-tabs: 5 → 4

`PaperShell` tabs become **Overview · Decisions · Book · Settings**.

| Old path | New |
|---|---|
| `/ai/practice` | Overview (rewritten) |
| `/ai/practice/decisions` | unchanged |
| `/ai/practice/holdings` | `/ai/practice/book` |
| `/ai/practice/engine` | redirect → `/ai/practice` (run controls moved to Overview) |
| `/ai/practice/settings` | unchanged |

`/ai/practice/holdings` redirects to `/ai/practice/book`. The legacy redirects in `App.jsx`
(`/paper/engine`, `/paper/holdings`, `/trading`) are re-pointed so none chains through
another redirect.

### Overview `/ai/practice`, top to bottom

1. **What this is** — one line under the stamp:
   "The strategy engine trades practice money here. Its rules decide; AI adds at most 30% to
   a trade's score. The AI autopilot is separate → AI Overview." (link to `/ai`).
2. **Live mode armed** band — moved as-is from `Trading.jsx`, shown only when
   `live_strategies` is non-empty.
3. **Now** — the engine sheets moved from `Trading.jsx` into a new `EngineNow` component,
   unchanged in behaviour:
   - *Intraday engine*: running/idle, Start (with `TradingControlBar`), each run's Stop and
     progress, auto-run badge, kill-switch and crashed-run notices.
   - *Long-term engine*: on/off, what it does and when, Scan now, pending and open counts.
   - Today's paper P&L (`PnlStatement`) and the pending-decisions banner (existing) sit
     directly below.
4. **Is it working** — new `StrategyReadiness` sheet, one row per strategy from
   `GET /settings/strategies/promotion`:
   - Ready: "Ready for real money" (and whether its live switch is on).
   - Not ready: "Paper only. Needs …" using the existing gap wording.
   - Link "Change in Settings ›" to `/ai/practice/settings`.
5. **Full track record** — the All / Intraday / Long term filter, the `Scorecard`, and the
   `TradeLedger`, in a section that is collapsed by default (`<details>`), filter inside it.

### Book `/ai/practice/book`

`Portfolio.jsx` as today (equity curve, open positions marked live, closed trades), plus the
**Executions** sheet (last 25 fills) moved from `Trading.jsx`. The Engine page's own
*Positions* sheet is dropped: Book's positions already cover it.

### Files

| File | Change |
|---|---|
| `frontend/src/pages/PaperOverview.jsx` | Rewritten to the order above |
| `frontend/src/components/paper/EngineNow.jsx` | New: intraday + long-term engine sheets and live-armed band, moved from `Trading.jsx` |
| `frontend/src/components/paper/StrategyReadiness.jsx` | New: per-strategy readiness rows |
| `frontend/src/utils/promotion.js` | New: `promotionGaps` moved out of `EngineSettings.jsx`, shared by both |
| `frontend/src/components/paper/EngineSettings.jsx` | Imports `promotionGaps` |
| `frontend/src/pages/Portfolio.jsx` | Adds the Executions sheet |
| `frontend/src/pages/Trading.jsx` | Deleted |
| `frontend/src/components/paper/PaperShell.jsx` | Four tabs (`grid-cols-4`) |
| `frontend/src/App.jsx` | Routes and redirects as in the table |
| `PRODUCT.md` | Practice rows rewritten to match |

## Error handling

Each sheet loads on its own and fails on its own, as the current pages do: a failed
promotion fetch shows "Couldn't load strategy readiness." in that sheet only; the rest of
the page still renders.

## Testing

- `promotionGaps` gets one small test (`frontend/src/utils/promotion.test.js`): a passing
  row gives no gaps; a row with no backtest and a failing profit-factor check names both.
  Run with `node --test frontend/src/utils/promotion.test.js` (the frontend has no test
  runner installed; `promotion.js` is a plain ES module, so none is added).
- `npm --prefix frontend run build` and `npm --prefix frontend run lint` pass; backend suite
  untouched.
- Manual at phone width (375px): nothing overflows; four tabs fit on their short names.
- Manual: `/ai/practice/engine`, `/ai/practice/holdings`, `/paper/engine`, `/trading`
  each land on the right page in one hop.
