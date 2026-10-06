# Practice redesign — Engine, Book, Strategies

2026-10-06. Status: approved in conversation (part 1), awaiting spec review.

## Intent

Said by the user: Practice → Engine and Book have very bad UX. All three jobs matter
equally — *what is the engine doing now*, *how is my practice money doing*, *is any
strategy good enough for real money*. Practice positions are sold/added by hand only
rarely. The verdict lives in the Library tab, renamed Strategies.

Found on the pages (screenshots 2026-10-06): the same money appears four times across two
pages (Today net, Month to date ×2, Realised all time) and before charges, while the
strategy scorecard is after charges; "Is it working" (the verdict) sits collapsed at the
bottom; "Awaiting your decision" duplicates AI → Decisions; every open position is a large
card with Sell/Add; the banner and intro paragraph repeat.

Success: each job has one tab that answers it in the first screen on a phone; every
practice P&L is net of charges; no figure appears on two tabs.

## Tabs

`PRACTICE_TABS`: **Engine** `/practice` · **Book** `/practice/book` · **Strategies**
`/practice/strategies` · **Setup** `/practice/setup`. `/practice/library` redirects to
`/practice/strategies`. The dashed "Practice money" marker (`PaperShell`) stays, one line;
the intro paragraph on Engine goes.

## Engine `/practice` — what it is doing now

In order:
1. **Intraday engine** row: state (idle / running with live progress from `EngineNow`),
   Start / Stop, run settings line. Unchanged behaviour, tighter layout.
2. **Long-term engine** row: on / off, "next scan 16:00 IST", Scan button, "N open
   long-term positions". The explanatory prose is removed (it is in the handbook).
3. **Today**: one figure, **net after charges**, with realised, unrealised, trades
   (W / L) beneath. No Month to date here.
4. **Traded today**: today's fills, compact (time, side, qty, symbol, price), newest
   first, up to 10 with "Show all".
5. One line linking to Strategies: "13 strategies · 0 ready for real money ›".

Removed from Engine: Month to date, "Awaiting your decision" banner, Is it working, Full
track record, What the engine learned (the last three move to Strategies).

## Book `/practice/book` — how the practice money is doing

1. **Headline**: net P&L after charges with a **Today / Month / All time** switch (default
   All time), closed trades and win rate for that period, and the curve of closed
   round trips for that period beneath.
2. **Open positions**: one compact row each — logo + symbol, qty @ avg, value, unrealised
   (labelled "at last close" when the market is closed). Tapping a row reveals Sell / Add
   (the existing order actions). A total row for unrealised.
3. **Open orders** (paper limit orders), when any — unchanged.
4. **Executions**: latest 10, "Show more" to the 25 the API returns; meta "latest N of M".

Removed: the separate Month to date sheet (the switch covers it).

## Strategies `/practice/strategies` — is any of it good enough

Replaces `Library.jsx`:
1. **Summary**: counts of ready for real money / close / losing, from the library
   endpoint's statuses.
2. **Intraday / Long-term** filter (existing).
3. **One row per strategy**: name, status badge, net record line (trades, net, profit
   factor — `recordLine`), and what it still needs to go live (from the same promotion
   data `StrategyReadiness` reads). Tap to expand best-when / avoid-when / style.
   "Live switches in Setup ›".
4. **Track record** (existing `Scorecard`: overall, day by day, by strategy vs NIFTY) with
   its Intraday / Long term / All filter, open by default; `?book=` still selects it.
5. **What the engine learned** (`LearningSheet`), collapsed, fetched on open.

## One money rule

Every practice P&L is net of charges. `backend/analytics.py::compute_pnl` adds, for
`today` and `month`, `costs` (sum of closed trades' `costs`) and `net` (`realized -
costs`), and the response gains `all_time` `{realized, costs, net, trades, wins}`. Fields
already returned keep their meaning, so other callers (Today's page, the chat) are
unaffected.

## Errors and states

Each block loads on its own and shows its own "Could not load …"; empty states say what
will appear ("No fills today — the intraday run is idle"). Market closed: unrealised is
labelled "at last close".

## Testing

- Backend: `compute_pnl` returns `costs`, `net` per period and `all_time`, net =
  realised − costs; existing fields unchanged (`backend/tests/` analytics tests).
- Frontend: lint + build; a node test for the period selector's maths if it is
  extracted to a util (`utils/practice.js`); screenshots at 390 px and 1440 px of the
  three tabs, page width 390 on phone.
- Docs: PRODUCT.md Practice rows; handbook Trading & Money "Practice" section.

## Out of scope

Live switches move (stay in Setup); Setup redesign; the Decisions page; new metrics.
