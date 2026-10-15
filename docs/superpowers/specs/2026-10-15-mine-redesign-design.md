# Mine redesign: the trader's own account, with a past, a to-do list and tax

## Context

Owner (2026-10-15): "Mine is useless right now." Scan of the code after Phase 19:

- **Holdings** (`pages/MyPortfolio.jsx`, 653 lines) is one statement behind five sub-tabs (Holdings ·
  Plan · Rebalance · Mix · Review). Plan and Review are AI text walls behind a manual "Analyse now".
  Its value card duplicates Today's "Your account".
- **Ideas** (`pages/Decisions.jsx`) is empty by design: only strategies proven on the AI account
  (`risk/paper_gate.py::for_mine`) reach it, which takes weeks.
- **Trades / Habits** (`pages/Journal.jsx`) need imported history. Habits needs many round trips;
  the owner mostly holds.
- **Present tense only.** `portfolio_snapshots` keeps every review, yet nothing shows value over
  time, XIRR, realised gains, tax, dividends or upcoming results.
- **Nothing is the owner's.** No reason-for-buying, no own target / stop / review date, no page per
  holding.

## Decisions (owner, 2026-10-15)

| Question | Answer |
|---|---|
| Jobs Mine must do | Performance over time · What needs me now · Tax (India) · Own thesis per stock (all four) |
| Ideas tab | **Fold into the action list.** No Ideas tab; proven swing ideas, ADD verdicts and rebalance buys appear in "Needs you" when they exist. Gate unchanged |
| Mine vs Today | **Today = glance, Mine = depth.** Today keeps a 3-line pulse + top 3 actions linking into Mine. No duplicated cards |
| Trade history source | Upstox only; owner will run the import. `POST /journal/import/upstox-history` already exists |

Unchanged invariants: proven-only ideas for Mine; nothing trades Mine without the owner's taps;
verdicts stay admin-gated (`portfolio/digest.py::verdicts_visible`); AI cap and the single conviction
formula are untouched (this work adds no scoring).

## Navigation

Mine: **Overview** `/mine` · **Holdings** `/mine/holdings` · **Tax** `/mine/tax` · **Journal**
`/mine/journal`, plus **Stock** `/mine/stock/:symbol` (no tab; reached from rows and actions).

| Old path | New |
|---|---|
| `/mine` (redirected to holdings) | Overview |
| `/mine/ideas` | `/mine` (Needs you) |
| `/mine/trades` | `/mine/journal` |
| `/mine/habits` | `/mine/journal?tab=habits` |

`MINE_TABS` in `components/layout/sections.js` becomes the four tabs; the Mine section's `path`
becomes `/mine`, and its badge counts open "Needs you" items (was: pending ideas).

## Screens

### Overview `/mine`

1. **Headline**: current value, today's move, total gain, **XIRR**, and **NIFTY's XIRR on the same
   cash flows** (same rupees in on the same days). "As of" when the broker is logged out.
2. **Value curve**: ranges 1M · 6M · 1Y · All. Three lines: value, net invested, NIFTY-equivalent
   value. From `mine_daily`. Recharts (already used by `TradingChart`); follow the `dataviz` skill.
3. **Needs you**: the ranked action list (below). Each row: holding, one-line reason, one action
   (open ticket, open stock page, approve idea, dismiss, snooze 7 days). Empty: "You're clear."
4. **What drove it**: top 3 and bottom 3 holdings by rupee contribution, this month and all time.
5. **Mix**: sector bars, largest holding %, top-five %, correlated pairs (today's `Concentration`,
   moved here).

### Holdings `/mine/holdings`

- Phone: one line per holding: symbol, weight, value, day %, total %, verdict stamp, and a thin
  bar for progress from cost to the owner's target when one is set. Desktop: same columns as a
  `Statement`.
- Sort: weight (default), day move, total gain, verdict. Filter chips: Needs you · Stocks · Funds.
- Row tap opens the Stock page (no inline expand).
- "Plan new money" opens the existing `components/portfolio/Rebalance.jsx` in a sheet.

### Stock `/mine/stock/:symbol`

1. **Position**: qty, avg cost, value, gain, **this holding's XIRR**, held since. **Lots table**:
   buy date, qty, price, days to long-term (or "long-term"), unrealised gain, est. tax if sold today.
2. **Chart**: daily closes from `daily_bars` with buy/sell markers from journal trades and the
   owner's target / stop as reference lines.
3. **Your thesis** (editable): why I bought (text), target price, stop price, review-by date.
   Target and stop drive alerts (below).
4. **Verdict**: current verdict + reasons (today's `Detail` component content) and **verdict
   history**: one row per change, from `portfolio_snapshots`.
5. **Coming up**: next results date, next ex-dividend date + amount (`corporate_events`).
6. **Dividends received**: estimated from ex-dates × quantity held on that date.
7. **News**: this symbol's scored headlines (`news_items`, as `digest.headlines_for`).
8. **Actions**: Sell / Add via `OrderTicket` (account `mine`); link to Research → stock.

A holding not in the latest snapshot (sold) still opens: position section reads "Sold", lots and
journal history remain.

### Tax `/mine/tax`

FY selector (Indian FY, Apr–Mar; default current).

- **Realised this FY**: FIFO from journal trades. Short-term (held ≤ 365 days, 20%) and long-term
  (> 365 days, 12.5% on the part above ₹1.25 lakh). Shows LTCG exemption used / left, charges, and
  estimated tax.
- **Unrealised now**: per lot, split short / long term.
- **Turning long-term soon**: lots crossing 365 days within 60 days with a gain; "wait N days,
  save ₹X" (STCG − LTCG on that gain).
- **Before 31 March** (shown Jan–Mar, and always reachable): (a) **loss harvest**: lots at a loss
  that would offset realised gains, with the tax saved; (b) **gain harvest**: long-term gains that
  fit in the unused ₹1.25 lakh exemption (sell and rebuy to reset cost).
- Every figure reads "Estimate, not tax advice". Lots the journal cannot date show as "unknown
  quantity" and are excluded from figures, with a link to import history.
- Rates and threshold live in one place, `backend/mine/tax.py` (moved from
  `portfolio/rebalance.py`, which then imports them).

Not covered (stated on the page): pre-2018 grandfathered cost (lots bought before 2018-02-01 are
flagged, not computed), F&O / intraday business income, set-off against other income.

### Journal `/mine/journal`

Today's `Journal.jsx` with its `view` prop turned into two inner tabs (Trades · Habits) plus the
"Orders placed from NeoTrade" ledger it already renders. No other change in this redesign.

### Today

Replace the "Your account" sheet with: value · today's move · total gain on one line, then the top 3
"Needs you" items, then "See all in Mine ›". "Do today" keeps its non-holding items (logins,
waiting cards, guardrail alerts) and drops the holding items now owned by Needs you.

### Cut

- Holdings sub-tabs **Plan** (AI action plan) and **Review** (AI write-up), and the "Analyse now"
  button. The daily 16:00 review still runs and still writes verdicts; the AI `note` per holding
  stays and shows on the Stock page.
- **Ideas** page (`Decisions.jsx`): its content moves into Needs you; `WaitingCards` moves to
  Overview above Needs you.
- **Mix** sub-tab (content moves to Overview), **Habits** tab (moves into Journal).

## The action list ("Needs you")

`backend/mine/actions.py::build(db, user_id, now) -> list[Action]`, one function used by
`GET /mine/actions`, Today and both Telegram digests.

`Action = {id, kind, symbol, title, detail, rank, action: {type, ...}, at}`. `id` is stable:
`f"{kind}:{symbol}:{key}"` where `key` pins the instance (verdict pair, level, event date, idea
id), so a dismissed item stays dismissed until something new happens.

| kind | Fires when | Action | Rank |
|---|---|---|---|
| `stop_hit` | price ≤ owner's stop | Sell ticket | 10 |
| `target_hit` | price ≥ owner's target | Sell ticket / edit thesis | 20 |
| `verdict_worse` | `portfolio/rules.py::worsened(prev, now)` on latest review | Stock page | 30 |
| `bad_news` | material negative scored headline in 36h (as `digest.headlines_for`, direction down) | Stock page | 40 |
| `idea` | pending proven idea (`for_mine` filter, existing list endpoint) | Approve live / decline | 45 |
| `review_due` | owner's review-by date ≤ today | Stock page | 50 |
| `results_soon` | results within 7 days | Stock page | 60 |
| `overweight` | weight > size limit (existing `overweight` reason code) | Rebalance | 70 |
| `ltcg_soon` | lot with gain turns long-term within 30 days | Stock page (lots) | 80 |
| `harvest` | Jan–Mar and a loss or gain harvest exists | Tax page | 85 |
| `ex_dividend` | ex-date within 7 days | none (info) | 90 |
| `add` | ADD verdict with rebalance suggestion | Buy ticket | 95 |

Sort by rank, then recency. Admin gate: `verdict_worse` and `add` only when `verdicts_visible`.

State: `mine_action_state {user_id, action_id, state: dismissed|snoozed, until}`. Dismissed hides
that id for good; snoozed hides until `until`. `POST /mine/actions/{id}/dismiss`,
`POST /mine/actions/{id}/snooze` (7 days).

**Alerts.** `stop_hit` and `target_hit` also go to Telegram once per id, from the existing 60s
exit-alert path (`suggestions/exits.py` area, which already alerts on `<user>:mine` trades),
priced from ingest quotes. Dedup key in Redis per action id.

## Backend

New package `backend/mine/`; every collection carries `user_id`.

| Module | Does | Reuses |
|---|---|---|
| `lots.py` | `lots(trades, symbol)` FIFO open lots + realised matches (date, qty, buy price, sell price, sell date); `reconcile(lots, broker_qty)` marks the shortfall as unknown | `portfolio/scorecard.py::open_lots` logic (moved here; scorecard imports it) |
| `history.py` | `mine_daily {user_id, date, value, invested, nifty_value, flows}`; `backfill(user_id)` replays journal trades over `daily_bars` closes from first trade; `write_today(user_id)` from the 16:00 pass; `xirr(flows, end_value)` (Newton with bisection fallback, stdlib only) | `datalayer/bars.py::read`, `nifty_closes`; `portfolio/service.py::mine_holdings`, `quoted` |
| `tax.py` | `fy_report(trades, holdings, fy, today)`: realised ST/LT, exemption, est. tax, unrealised by lot, turning-long-term, harvest lists | `rebalance.charges`; rates moved here |
| `actions.py` | `build`, ranking, state filter | `digest.headlines_for`, `rules.worsened`, `paper_gate.for_mine`, `rebalance.suggest` |
| `thesis.py` | `holding_theses {user_id, symbol, why, target, stop, review_by, updated_at}` store | — |
| `events.py` | ingest loop `corporate_events {symbol, kind: results|ex_dividend, date, amount}` for held symbols, once a day, from yfinance `calendar` / `dividends`; marked `source="yfinance"` | `datalayer/worker.py` `Loop`, `mine_holdings` |

Backfill gap: if the journal holds less than the broker qty for a symbol, the curve before the first
known buy uses the snapshot's avg cost as a single "unknown date" lot from the first snapshot date.
The UI marks the curve "from <date>" when this happens.

Router `backend/routers/mine.py` (auth required, all scoped to `user.id`, account role `mine`):

| Endpoint | Returns |
|---|---|
| `GET /mine/overview` | headline (value, day, gain, xirr, nifty_xirr), drivers, mix, as_of |
| `GET /mine/history?range=1M\|6M\|1Y\|ALL` | `mine_daily` points |
| `GET /mine/actions` | ranked open actions |
| `POST /mine/actions/{id}/dismiss` · `/snooze` | 204 |
| `GET /mine/stock/{symbol}` | position, lots, xirr, thesis, verdict + history, events, dividends, news, closes, trades |
| `PUT /mine/thesis/{symbol}` | saved thesis (validate: prices > 0, review_by a date, why ≤ 2000 chars) |
| `GET /mine/tax?fy=2026` | FY report |

Jobs: scheduler 16:00 pass (`scheduler.py:127`, after `daily_reviews`) calls
`history.write_today` per user; the first call for a user with no `mine_daily` runs `backfill`.
Ingest gets `Loop("corp_events", 6 * 3600, events.loop)` that refreshes each held symbol at most
once a day. Telegram post-close (`digest.send_postclose`) and pre-market list the top 3 actions.

Prompts: none added. The per-holding AI `note` keeps its existing prompt.

## Phases

Each phase ships and deploys on its own.

| Phase | Ships | Done when |
|---|---|---|
| **M1 data** | `lots.py`, `history.py` (backfill + nightly + xirr), `GET /mine/history`, `/mine/overview` headline; owner runs Upstox import | `mine_daily` has a row per trading day since first trade for the owner; XIRR matches a hand check on a 3-flow fixture |
| **M2 Overview + actions** | `actions.py`, `thesis.py` store (no UI yet), state endpoints, Overview page, Today slim card, Mine badge, Telegram top-3 | `/mine` renders all five sections on a phone; dismiss survives reload; Today shows top 3 |
| **M3 Holdings + Stock** | Holdings list, Stock page, thesis editor, stop/target alerts | thesis saved → `target_hit` fires in a test with a mocked quote; Telegram once per id |
| **M4 Tax** | `tax.py`, `/mine/tax`, Tax page, `ltcg_soon` + `harvest` actions | fixtures cover ≤365/>365 boundary, exemption partly used, loss offset, unknown qty |
| **M5 events** | `events.py` ingest loop, Coming up, dividends, `results_soon` + `ex_dividend` actions, dividends in XIRR flows | held symbols have `corporate_events` rows within a day of deploy |
| **M6 cuts + docs** | delete Plan/Review/Mix sub-tabs, `Decisions.jsx`, old routes → redirects; PRODUCT.md surfaces, handbook, ROADMAP Phase 20 row | `npm run build` clean; no import of deleted components; handbook anchors resolve |

Order is fixed: M1 before everything (history and lots feed every screen); M4 needs M1's lots.
M2 and M3 can run as parallel worktree waves after M1; M5 after M2.

## Verification

- Backend: `cd backend && python -m pytest` per phase. New tests: lot FIFO with partial sells;
  reconcile shortfall; XIRR (known answer, all-negative, single flow); tax boundaries (day 365 vs
  366, exemption ₹1.25 lakh straddle, losses offset ST before LT); action ranking, stable ids,
  dismiss/snooze expiry; backfill with gaps in `daily_bars`; thesis validation; user scoping (user B
  cannot read user A's thesis/actions).
- Frontend: `npm run build` (not only vitest). Phone check at 375px for Overview, Holdings, Stock.
- Prod after each deploy: `/health` 200; `/mine/history` returns today's row after 16:00;
  `/mine/actions` responds under 1s.
- Deploy mode: ask once before the first push (host CLAUDE.md).

## Risks

- **History depth.** Upstox's trade-history API may not go back far. Lots it cannot date become
  "unknown" and are left out of tax figures; a P&L-statement CSV import is the follow-up if this
  bites.
- **yfinance events** can be late or wrong; shown as estimates with source.
- **Backfill cost.** One replay per user over `daily_bars`; bars for held symbols already exist
  (`bars.loop`). Missing bars → that day carries the previous close.
- **Tax rules change** (Budget). Rates live in one module with the effective date in a comment.
