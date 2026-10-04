# Order ticket: Buy/Sell on paper or my account, market or limit

Date: 2026-10-04 · Status: design approved in chat ("Yes"), awaiting spec review

Sub-project 2 of 4 (scanner → **order ticket** → one decisions inbox → research search page).

## Problem

A trader looking at a stock, a holding, a watchlist row or a scanner finding cannot act on it.
The only manual order path is the chat assistant's order card
(`backend/chat/actions.py`: `propose_order` → `chat_actions` card → `/chat/actions/{id}/confirm`),
and it is market-only.

## Goal

One order ticket, opened from four places, that places a **market or limit** order on
**Paper** (the practice book) or **Mine** (the user's own broker account, Upstox role `mine`),
through the same checks and confirmation the chat card already uses.

## Non-goals

- Never the AI account. The ticket has no `ai` option and the route rejects one.
- No stop-loss/GTT, no risk-based sizing, no F&O (declined or out of scope).
- No modify of resting orders from the ticket (chat's modify/cancel cards cover Mine;
  paper gets Cancel only).
- No reconciler for live orders: Mine fills reach holdings and the journal through the
  existing broker sync.

## Backend

### 1. Propose: `POST /orders/propose` (new `backend/routers/orders.py`)

Body:

```json
{"symbol": "ITC", "side": "BUY", "quantity": 10, "product": "CNC",
 "order_type": "LIMIT", "limit_price": 405.0, "venue": "paper"}
```

`side` BUY|SELL · `quantity` int > 0 · `product` CNC|MIS · `order_type` MARKET|LIMIT ·
`limit_price` required iff LIMIT · `venue` paper|live. Unknown fields rejected (an `account`
field cannot be smuggled in).

It runs `_order_checks` (extended, below), then stores a card with
`ChatActionStore.propose(user_id, "order", params, summary, venue, second_tap=venue == "live",
message="order ticket")` and returns the card (`id, kind, summary, venue, needs_second_tap,
expires_at`). A refusal → 409 with the `ActionRefused` message.

Summary copy: `{SIDE} {qty} {SYMBOL} · {delivery|intraday} · {market | limit ₹{price}} ·
~₹{value} on {paper|your account}`.

Confirm and cancel reuse `POST /chat/actions/{id}/confirm` and `/cancel` unchanged: atomic
claim, 5-minute expiry, every check re-run at confirm, second tap for live.

### 2. `_order_checks` / `_execute` learn LIMIT (`backend/chat/actions.py`)

Added to `_order_checks`, for both the ticket and chat cards:
- `order_type` defaults to `MARKET` (existing chat cards keep working).
- LIMIT: `limit_price > 0` and within ±20% of the fresh mark price, else
  `"Limit ₹{p} is more than 20% from the price ₹{m}; check the number."`
- Per-trade cap uses `limit_price` for LIMIT, the mark price for MARKET.
- **CNC sell ≤ held**: paper → open quantity in `LedgerStore.get_open_positions()`; live →
  `account_actions._held(adapter, symbol)`. Refusal: `"You hold {n} {SYMBOL}; a delivery sell
  can't be more than that."` MIS sells are not capped (intraday short, as at the broker).

`_execute` kind `order`:
- Live LIMIT is refused unless the `mine` adapter sends the limit price
  (`SUPPORTS_LIMIT`, Upstox today): `"Limit orders on your account need Upstox; place a market
  order or use Paper."` Angel One's adapter hard-codes MARKET and Kite's omits the price.
  The ticket rounds a limit to the ₹0.05 tick.
- **live**: `Order(order_type=params["order_type"], limit_price=params.get("limit_price"), …)`
  through `execute_live_order` unchanged. Result copy: MARKET as today; LIMIT not filled within
  the status checks → `"Resting at your broker: limit ₹{p}, {filled} of {qty} filled. It lasts
  until 15:30."`
- **paper MARKET**: as today (`execute_suggestion` at the mark).
- **paper LIMIT**: `paper_orders.place(...)` (below), which fills now if marketable, else rests.
  Result: `"Paper {SIDE} {qty} {SYMBOL} filled at ₹{price}."` or `"Paper limit ₹{p} is open
  until 15:30; it fills if the price gets there."`

### 3. Paper resting limits (new `backend/engine/paper_orders.py`)

Collection `paper_orders`, one doc per order:
`{id, user_id, symbol, side, quantity, product, limit_price, status: OPEN|FILLED|CANCELLED|EXPIRED,
created_at, filled_at?, fill_price?, session_date}` (`session_date` = IST date placed).

- `async place(db, user_id, params, mark, now) -> dict` — marketable (BUY: mark ≤ limit; SELL:
  mark ≥ limit) → fill now via `fill_on_paper` at **BUY min(mark, limit) / SELL max(mark,
  limit)** and store as FILLED; else store OPEN.
- `async sweep(db, mark_price, now) -> int` — for every OPEN order: if `now` (IST) is at or past
  15:30 or `session_date` < today → EXPIRED; else if the mark crossed the limit → fill via
  `fill_on_paper` **at the limit** (the mark is sampled once a minute, so the better-of rule
  would flatter the paper book on a fast move), FILLED. Claim each order atomically
  (`find_one_and_update` OPEN → FILLING) so a fill can never happen twice. Before filling a CNC
  sell, re-check holdings; if no longer held → CANCELLED with reason `"no longer held"`.
- `async list_open(db, user_id) -> list[dict]`, `async cancel(db, user_id, order_id) -> bool`
  (OPEN → CANCELLED, owner only).
- Loop `start(db)`: every 60 s, only while `in_session(now)`, plus one pass at or after 15:30 to
  expire; started from `server.py` startup next to `guardrail_monitor.start`. One mark lookup per
  distinct symbol per pass. A failed mark lookup skips that symbol for the pass.

Routes (same router): `GET /orders/paper` (open orders for the user) and
`POST /orders/paper/{id}/cancel` (404 when not the user's or not OPEN).

## Frontend

### `OrderTicket` (new `frontend/src/components/trading/OrderTicket.jsx`)

A modal sheet (fixed overlay; bottom sheet on phone, centred on desktop; focus trapped, Esc
closes). Props: `symbol`, `side` (default BUY), `venue` (default `paper`), `onClose`, `onDone`.

Fields: Buy | Sell · Paper | Mine · Delivery | Intraday · Market | Limit (+ price) · Quantity ·
estimated value (`qty × (limit or last price)`).

Flow:
1. **Review** → `POST /orders/propose` → shows the card's `summary`; refusals shown inline.
2. **Confirm** → `/chat/actions/{id}/confirm`. Mine: the response `NEEDS_SECOND_TAP` turns the
   button into **"Real money. Tap Confirm again"** (stamp colour), second tap sends
   `second_tap: true`.
3. Result line (the confirm `result` text), then `onDone()`.
Closing after Review without confirming → `/chat/actions/{id}/cancel`, so the card does not
linger in Today → Needs you.

Mine is disabled with `"Connect your broker and set it as My account in Settings"` (link
`/settings?tab=accounts`) when the user has no `mine` role.

### Entry points

| Where | Buttons | Default venue |
|---|---|---|
| Stock page header (`AnalysisCard`) | Buy · Sell | Paper |
| Watchlist rows (`Watchlist.jsx`) | Buy | Paper |
| Scanner findings (`ScannerPage.jsx`) | Buy | Paper |
| Mine → Holdings rows (`MyPortfolio.jsx`, equity only) | Sell · Add | Mine |
| Practice → Book rows (`Portfolio.jsx`) | Sell · Add | Paper |

Row buttons stop click propagation (rows already open the stock).

### Open paper orders

Practice → Book gets an **Open orders** sheet (hidden when empty): symbol, side, qty, limit,
placed time, **Cancel**. Refreshes after a ticket confirms and every 60 s while visible.

## Testing

- `test_orders_router.py`: propose MARKET/LIMIT paper and live cards; limit outside ±20% →
  409; cap uses the limit price; CNC paper sell over held → 409; MIS sell over held allowed;
  `account` field → 422; missing `limit_price` with LIMIT → 422; live card has
  `needs_second_tap`.
- `test_paper_orders.py`: marketable buy fills at min(mark, limit); resting buy fills on cross
  at the limit; no fill while not crossed; expires at 15:30 and on a later session date; cancel
  by owner only; sweep never fills twice (two concurrent sweeps); CNC sell no longer held →
  CANCELLED; user A's orders invisible to user B.
- `test_chat_orders.py` (extend): live LIMIT reaches the fake adapter with
  `order_type="LIMIT"` and `limit_price`; resting result copy; existing MARKET chat cards
  unchanged.
- Frontend: `npm run build` + lint.
