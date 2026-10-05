# Portfolio rebalance helper (holdings redesign, part C)

Date: 2026-10-05 · Status: design approved in chat, awaiting spec review

The holdings redesign ships in three parts, in the owner's order: **C** acting (this spec), **B** staying
informed (events, alerts, what changed), **A** money truth (tax view, XIRR, value chart). B and A get
their own specs.

## Decisions (owner)

1. Targets: a rule fills them, single stocks can be overridden.
2. Money: optional new money is used first; sells cover only what is still over target.
3. New names may be brought in from the watchlist and AI longterm picks, ticked by the user.
4. Each holding row shows its AI verdict as a one-tap action with the quantity filled in. A SELL
   verdict sells the whole holding. An ADD verdict buys up to the rebalance target.

## Safety

- Nothing is placed in bulk and nothing is placed without the user. Every suggested trade opens the
  existing `OrderTicket` pre-filled; the ticket's venue defaults to Paper, and a live order still needs
  My account plus the second tap (AGENTS.md).
- All reads and the saved targets are scoped to the authenticated user.
- AI longterm picks appear as candidates only where portfolio verdicts are visible
  (`AppSettingsStore.portfolio_verdicts`, the SEBI gate in `routers/portfolio.py`). The user's own
  watchlist always appears: targets the user sets are a calculator, not advice.

## Backend

### `backend/portfolio/rebalance.py` (pure, no I/O)

`plan_rebalance(holdings, candidates, targets, new_money, lots, sectors) -> dict`

**Universe.** Priced holdings whose kind is STOCK or ETF, plus ticked candidates (each with a price).
Mutual funds and unpriced holdings are excluded and listed in `excluded` with the reason.
`total = sum(current value of the universe) + new_money`.

**Targets** (weights summing to at most 1):
- Overrides are fixed weights. Overrides summing above 100% are rejected (422).
- The rule fills the remaining weight `R = 1 - sum(overrides)` across the other names:
  - `equal`: each gets `R / n`.
  - `cap`: each gets its current weight (a ticked candidate gets `R / n` as a starter slot),
    scaled to sum to `R`. Then any name above `max_stock_pct`, and any sector above
    `max_sector_pct`, is clipped. The freed weight is spread over unclipped names in proportion
    to their weight. Repeat until stable (at most 10 passes). Weight nobody can absorb stays cash.
- Sector comes from the snapshot's `sector`. ETFs and names without a sector are exempt from the sector cap.

**Trades.** For each name, `delta = target_weight × total − current_value`.
- Sell when `delta < 0`: quantity `floor(|delta| / price)`, never more than held.
- Buy when `delta > 0`: quantity `floor(delta / price)`. A name whose single share costs more than
  `delta` gets no buy and is listed in `skipped` ("one share costs more than its slot").
- Cash available for buys is `new_money + sell proceeds − all charges`. When buys exceed it, every
  buy is scaled down by the same factor (whole shares, floor).
- Charges come from `calculate_indian_costs` (CNC, DP charge on sells). A trade whose charges exceed
  1% of its value is dropped and listed in `skipped` ("charges above 1% of the trade").

**Tax on sells.** The sell quantity is matched FIFO against the snapshot's journal lots:
- Lots held more than 365 days are long-term; the rest are short-term.
- The `gain` is split into short-term and long-term.
- `est_tax = 20% × short-term gain + 12.5% × long-term gain`. It is labelled "before the ₹1.25L
  long-term exemption", and losses give 0.
- Quantity the journal cannot date is `unknown_qty`, with no tax figure.

**Output.**
```
{ "total": float, "cash_left": float,
  "trades": [{ "symbol", "side", "quantity", "price", "value", "charges",
               "weight_now", "weight_after", "target_weight",
               "tax": {"short_gain", "long_gain", "unknown_qty", "est_tax"} | null }],
  "skipped": [{"symbol", "reason"}], "excluded": [{"symbol", "reason"}],
  "stale_since": iso | null }
```
Sells are listed first, then buys, each by value descending.

### Row actions (`suggested` on each holding)

`target_gaps(holdings, targets, sectors) -> {symbol: weight_gap}` holds the target maths from
`plan_rebalance`, and `plan_rebalance` calls it, so there is one copy of that maths. There are
no candidates and no new money.

`GET /portfolio`, only when verdicts are visible, adds `suggested` to each STOCK or ETF row:
- `SELL` verdict: `{"side": "SELL", "quantity": held quantity, "price": last price}`.
- `ADD` verdict: buy `floor(gap × total / price)` shares. No cash scaling, because broker cash is
  unknown. If that is 0 or less, it returns `{"at_target": true}` and no trade.
- The 1% charges filter applies. A dropped trade gives `{"skipped": reason}`.
- `HOLD`, `REVIEW`, `KEEP` and mutual funds: `suggested` is null.

When verdicts are hidden, `present()` sets `suggested` to null on every row, alongside the
existing masking.

### Prefs

`rebalance_targets` (default):
```
{"rule": "cap", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}
```
It is validated in `routers/settings.py`:
- `rule` is `equal` or `cap`.
- Each percentage is a number with `0 < pct ≤ 100`.
- At most 100 overrides.

### `routers/portfolio.py`

- `GET /portfolio/rebalance/candidates` lists the user's watchlist symbols not held, plus open
  LONGTERM suggestion symbols when verdicts are visible. Each comes with a last close (one batched
  yfinance download) and a `source` field (`watchlist` or `ai`).
- `POST /portfolio/rebalance` takes `{new_money: ≥0, candidates: [symbol] (max 20), targets?}`.
  It runs on the latest snapshot, with candidate prices fetched server side. `targets` defaults
  to the saved prefs and is not saved by this call. It returns the output above. With no snapshot
  it returns 409 "Refresh your portfolio first". It is rate-limited per user with
  `backend/rate_limit.allow` (10 per minute, 429 above that).

## Frontend

- **`OrderTicket`** gains optional `quantity` and `limitPrice` props that pre-fill the form; with
  `limitPrice`, the order type starts as LIMIT. Everything else is unchanged.
- **`MyPortfolio.jsx`** gets a new **Rebalance** tab between Holdings and Mix
  (`components/portfolio/Rebalance.jsx`):
  - Rule picker (Equal / Cap), with the two cap fields under Cap.
  - Per-stock override field in each holding row.
  - "Add ₹" field.
  - Candidates list with checkboxes and source badges.
  - A **Calculate** button. Targets are saved via `/settings/preferences` when Calculate is pressed.
  - Results: a phone list and a desktop statement. Each trade row shows side, quantity, ₹ value,
    weight now → after, and tax on sells, with a **Trade** button that opens the pre-filled ticket.
  - Skipped and excluded rows are shown with their reasons.
  - A stale-price warning shows when `stale_since` is set.
- **Holding rows** (phone list and desktop statement): when `suggested` has a trade, the verdict
  stamp becomes a button, **SELL 12 · ₹4,320** or **BUY 5 · ₹1,850**. One tap opens `OrderTicket`
  pre-filled (side, quantity, LIMIT at last price, venue Paper). Paper places on one confirm. Mine
  keeps the second tap. `at_target` shows "at target" and `skipped` shows its reason; neither has
  a button. The existing Sell / Add buttons stay for a manual size.
- **Plan tab**: unchanged. The plan is a markdown write-up with no per-trade items, and each
  holding row already has Sell / Add buttons.

## Testing (pytest, `backend/tests/test_rebalance.py`, plus router tests)

- Equal weight over held and ticked names.
- Cap: a stock above the cap is trimmed and the freed weight goes to the others.
- Sector cap.
- Overrides beat the rule; overrides above 100% give 422.
- New money is used before any sell, so an underweight book with enough new money has no sells.
- Buys scaled down when cash runs short.
- A share costing more than its slot is skipped.
- Charges filter.
- The short-term/long-term split and estimated tax.
- Undated lots are reported as `unknown_qty`.
- Mutual funds and unpriced holdings are excluded.
- `weight_after` sums to at most 100%.
- Row actions: SELL suggests the full holding; ADD suggests the target gap; ADD at or above
  target gives `at_target`; HOLD gives null; hidden verdicts null out `suggested`.
- Router: AI candidates are hidden when verdicts are not visible; another user's snapshot is
  never read; no snapshot gives 409.
- Frontend: `npm run build`, plus a vitest test that the ticket's pre-filled quantity and limit
  appear in the form.

## Out of scope

- Bulk "place all".
- Auto-rebalancing on a schedule.
- Tax-loss harvesting (part A).
- Mutual fund rebalancing.
