# Order Ticket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Buy/Sell ticket, opened from five places, that places market or limit orders on Paper or Mine through the chat card's existing checks and confirmation, with resting paper limits.

**Architecture:** `_order_checks`/`_execute` in `backend/chat/actions.py` learn LIMIT, the ±20% band and the CNC-oversell guard. A new `backend/engine/paper_orders.py` holds resting paper limits plus a 60 s sweep loop. A new `backend/routers/orders.py` proposes ticket cards and lists/cancels paper orders; confirm/cancel stay on `/chat/actions/*`. Frontend gets one `OrderTicket` modal wired into five pages and an Open orders sheet.

**Tech Stack:** FastAPI, Motor/mongomock_motor, pytest; React 19 + Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-order-ticket-design.md`

## Global Constraints

- Never the AI account: no `ai` option in the ticket; `POST /orders/propose` body uses `extra="forbid"` so `account` → 422.
- Confirm/cancel only through existing `POST /chat/actions/{id}/confirm|cancel`. Live cards `needs_second_tap=True`.
- `order_type` defaults to `MARKET`; existing chat MARKET cards behave exactly as before.
- LIMIT: `limit_price > 0` and within ±20% of the fresh mark; cap uses `limit_price` for LIMIT.
- CNC sell ≤ held (paper: open ledger position; live: `account_actions._held`). MIS sells uncapped.
- Paper limit fill price: BUY `min(mark, limit)`, SELL `max(mark, limit)`, booked via `fill_on_paper`.
- Paper orders expire at 15:30 IST or on a later session date. Every `paper_orders` doc carries `user_id`.
- Copy strings exactly as in the spec.
- Frontend check is `npm run build` + `npm run lint`.

## Review Focus

1. **Double fill under concurrent sweeps / sweep vs cancel race** → atomic OPEN→FILLING claim; a cancelled order never fills. Test in Task 2.
2. **Ticket closed after Review (Esc, backdrop, route change)** → card cancelled, nothing left in Today → Needs you. Covered by Task 4's close handler; check manually.
3. **Mark lookup fails for one symbol during a sweep** → that symbol skipped, other symbols still processed, loop survives. Test in Task 2.
4. **Limit price typed with a stray digit (₹4050 for ₹405)** → ±20% refusal with the spec copy. Test in Task 1.
5. **Live LIMIT not filled within the status checks** → "Resting at your broker…" copy, no false "filled". Test in Task 1.

---

### Task 1: LIMIT, band and oversell in the shared order checks

**Files:**
- Modify: `backend/chat/actions.py` (`_order_checks` ~165-190, `_execute` kind `order` ~405-418)
- Test: `backend/tests/test_chat_actions.py` (extend; reuse the `env` fixture)

**Interfaces:**
- Produces: `params` for kind `order` may carry `order_type: "MARKET"|"LIMIT"` (absent = MARKET) and `limit_price: float|None`. `_order_checks(db, user_id, params, credentials) -> tuple[float, adapter|None]` unchanged signature; `price` returned is still the fresh mark.
- Produces: `async def _held_on_paper(db, user_id, symbol) -> int` in `actions.py` (open quantity in `LedgerStore(db, user_id).get_open_positions()`, 0 if none).
- Consumes (Task 2, imported lazily inside `_execute` to avoid a cycle): `paper_orders.place(db, user_id, params, mark, now) -> dict` returning the stored doc (`status` FILLED or OPEN, `fill_price` when FILLED).

- [ ] **Step 1: Write the failing tests** (add `get_positions`/`get_holdings` to the test `_Broker`, returning `{}` and `[Holding(symbol="INFY", quantity=5, ...)]`)

```python
async def test_limit_outside_band_is_refused(env):            # mark 1500; limit 1801 and 1199 → ActionRefused "more than 20% from the price"
async def test_cap_uses_limit_price(env):                     # cap 20000; LIMIT 1250 × 16 = 20000 passes; MARKET 16 × 1500 refused
async def test_cnc_paper_sell_over_held_is_refused(env):      # paper ledger holds 3 INFY; CNC SELL 4 → "You hold 3 INFY; a delivery sell can't be more than that."
async def test_mis_sell_is_not_capped_by_holdings(env):       # no holding; MIS SELL 5 on paper passes checks
async def test_cnc_live_sell_over_held_is_refused(env):       # broker holdings 5; CNC SELL 6 live → refused
async def test_live_limit_reaches_broker_as_limit(env):       # confirm live LIMIT 1490 ×2 (second tap) → env["broker"].placed[0].order_type == "LIMIT" and .limit_price == 1490
async def test_live_limit_resting_copy(env):                  # broker status ACKNOWLEDGED, filled 0 → result startswith "Resting at your broker: limit ₹1,490.00, 0 of 2 filled."
async def test_market_chat_card_unchanged(env):               # params without order_type → paper fill copy exactly as before
```

Seed paper holdings by `execute_suggestion({"symbol": "INFY", "side": "BUY", "quantity": 3, "mode": "LONGTERM"}, LedgerStore(db, user_id="alice"), 1500.0)`. Drive checks with `actions._order_checks(...)` directly and live confirms by storing a card with `ChatActionStore(db).propose(...)` then `confirm(..., second_tap=True)`.

- [ ] **Step 2: Run, verify they fail**

Run: `python3 -m pytest backend/tests/test_chat_actions.py -q -p no:cacheprovider`
Expected: the 8 new tests FAIL (no band/oversell/limit handling); existing tests PASS.

- [ ] **Step 3: Implement in `backend/chat/actions.py`**

`_order_checks`: after the instrument check, compute `limit = params.get("limit_price")` for LIMIT and validate band; `basis = limit or price` for the cap; CNC SELL → paper `_held_on_paper`, live `account_actions._held(adapter, symbol)[0]` (after the adapter is resolved). `_execute` kind `order`: pass `order_type`/`limit_price` into the live `Order`; LIMIT status not FILLED → resting copy; paper LIMIT → `paper_orders.place(...)` and the two paper result strings from the spec.

- [ ] **Step 4: Run, verify they pass**

Run: `python3 -m pytest backend/tests/test_chat_actions.py backend/tests/test_chat_orders.py -q -p no:cacheprovider`
Expected: all PASS. (`test_live_limit_*` and paper LIMIT paths that need Task 2 are the only ones touching `paper_orders`; paper LIMIT is tested in Task 2.)

- [ ] **Step 5: Commit**

```bash
git add backend/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "feat(orders): limit orders, ±20% band and delivery-oversell guard in the shared order checks"
```

---

### Task 2: Resting paper limits and the sweep loop

**Files:**
- Create: `backend/engine/paper_orders.py`
- Modify: `backend/server.py` (startup: `paper_orders.start(db.db)` next to `guardrail_monitor.start`)
- Test: `backend/tests/test_paper_orders.py`

**Interfaces:**
- Produces (in `backend/engine/paper_orders.py`):
  - `async def place(db, user_id: str, params: dict, mark: float, now: datetime) -> dict`
  - `async def sweep(db, mark_price: Callable[[str], Awaitable[float]], now: datetime) -> int` (returns orders changed)
  - `async def list_open(db, user_id: str) -> list[dict]` (no `_id`)
  - `async def cancel(db, user_id: str, order_id: str) -> bool`
  - `def start(db) -> asyncio.Task` (60 s loop; marks via `backend.chat.actions._mark_price`; runs `sweep` while `in_session(now)` and once more at/after 15:30 each day to expire)
- Doc fields exactly as the spec: `id, user_id, symbol, side, quantity, product, limit_price, status, created_at, filled_at, fill_price, session_date` (+ `reason` when CANCELLED by sweep).

- [ ] **Step 1: Write the failing tests** (`mongomock_motor`; `OPEN = datetime(2026, 10, 5, 10, 0, tzinfo=IST)`)

```python
async def test_marketable_buy_fills_now_at_min_of_mark_and_limit():   # mark 400, BUY limit 405 → FILLED, fill_price 400, one ledger trade
async def test_resting_buy_fills_on_cross_at_limit():                 # place at mark 412 → OPEN; sweep with mark 399 → FILLED, fill_price 399 (BUY = min(mark, limit))
async def test_no_fill_while_not_crossed():                           # sweep with mark 401 → still OPEN, sweep returns 0
async def test_expires_at_close_and_next_session():                   # sweep at 15:30 IST → EXPIRED; separately session_date yesterday at 10:00 → EXPIRED
async def test_cancel_owner_only():                                   # bob cancel alice's → False; alice → True, status CANCELLED; cancelled never fills on a later crossing sweep
async def test_concurrent_sweeps_fill_once():                         # asyncio.gather(sweep, sweep) on a crossed order → exactly one ledger trade
async def test_cnc_sell_no_longer_held_is_cancelled():                # rest CNC SELL 3 with 3 held; sell holding elsewhere; crossing sweep → CANCELLED, reason "no longer held"
async def test_mark_failure_skips_symbol_only():                      # two symbols; mark raises for one → other still fills, sweep returns 1
async def test_list_open_is_per_user():                               # alice and bob each rest one → list_open("alice") has only alice's
```


- [ ] **Step 2: Run, verify they fail**

Run: `python3 -m pytest backend/tests/test_paper_orders.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: backend.engine.paper_orders`.

- [ ] **Step 3: Implement `backend/engine/paper_orders.py` and the startup line**

Fill via `fill_on_paper(LedgerStore(db, user_id=...), Order(order_type="LIMIT", limit_price=..., product=..., strategy_name="ticket", ...), price, now)`. Claim with `find_one_and_update({"id", "status": "OPEN"}, {"$set": {"status": "FILLING"}})`; on fill set FILLED, on any exception during fill revert to OPEN and log. One `mark_price` call per distinct symbol per sweep; exceptions skip that symbol. Loop body wrapped in try/except like `guardrails/monitor.py`.

- [ ] **Step 4: Run, verify they pass; then Task 1's paper-LIMIT path end to end**

Add to `test_chat_actions.py`: `test_paper_limit_card_rests_then_fills` (confirm paper LIMIT 1490 at mark 1500 → result "Paper limit ₹1,490.00 is open until 15:30…"; `paper_orders.sweep` with mark 1489 → FILLED).
Run: `python3 -m pytest backend/tests/test_paper_orders.py backend/tests/test_chat_actions.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/engine/paper_orders.py backend/server.py backend/tests/test_paper_orders.py backend/tests/test_chat_actions.py
git commit -m "feat(orders): resting paper limit orders with a 60s sweep, expiring at 15:30"
```

---

### Task 3: Orders router

**Files:**
- Create: `backend/routers/orders.py`
- Modify: `backend/server.py` (mount like `chat_actions`: `prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)]`)
- Test: `backend/tests/test_orders_router.py`

**Interfaces:**
- Consumes: `_order_checks`, `ChatActionStore.propose`, `ActionRefused` (Task 1); `paper_orders.list_open`, `paper_orders.cancel` (Task 2).
- Produces: `router = APIRouter(prefix="/orders", tags=["Orders"])`
  - `POST /orders/propose` body `TicketRequest(BaseModel, extra="forbid")`: `symbol: str, side: Literal["BUY","SELL"], quantity: int (gt=0), product: Literal["CNC","MIS"], order_type: Literal["MARKET","LIMIT"] = "MARKET", limit_price: Optional[float] = None, venue: Literal["paper","live"]`; model validator: `limit_price` required iff LIMIT. Returns the card dict. Symbol normalised `strip().upper().removesuffix(".NS")`.
  - `GET /orders/paper` → `list_open`; `POST /orders/paper/{order_id}/cancel` → `{"status": "CANCELLED"}` or 404.
  - Dependency `def _db()` returning `db.db` (overridable like `chat_actions._db`).

- [ ] **Step 1: Write the failing tests** (TestClient; override `get_current_user`, monkeypatch `orders._db` and `actions._mark_price` / `actions._active_broker` / `actions._now` as in `test_chat_actions.env`)

```python
def test_propose_paper_limit_returns_card():          # 200; summary == "BUY 2 INFY · delivery · limit ₹1,490.00 · ~₹2,980 on paper"; needs_second_tap False
def test_propose_live_card_needs_second_tap():        # venue live → needs_second_tap True, summary ends "on your account"
def test_limit_band_is_409():                         # limit 1801 at mark 1500 → 409, detail mentions "20%"
def test_account_field_is_422():                      # {"account": "ai", ...} → 422
def test_limit_without_price_is_422():                # order_type LIMIT, no limit_price → 422
def test_paper_orders_list_and_cancel():              # rest one via paper_orders.place → GET lists it; cancel → 200; cancel again → 404
def test_cannot_cancel_other_users_paper_order():     # bob's order id as alice → 404
```

- [ ] **Step 2: Run, verify they fail**

Run: `python3 -m pytest backend/tests/test_orders_router.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: backend.routers.orders`.

- [ ] **Step 3: Implement `backend/routers/orders.py` and mount it**

Summary string per the spec (`delivery`/`intraday`, `market` or `limit ₹{p:,.2f}`, `~₹{value:,.0f}`, `paper`/`your account`). `ActionRefused` → 409.

- [ ] **Step 4: Run, verify they pass, then the full suite**

Run: `python3 -m pytest backend/tests/test_orders_router.py -q -p no:cacheprovider && python3 -m pytest -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/orders.py backend/server.py backend/tests/test_orders_router.py
git commit -m "feat(orders): POST /orders/propose for ticket cards; list and cancel open paper orders"
```

---

### Task 4: OrderTicket and entry points

**Files:**
- Create: `frontend/src/components/trading/OrderTicket.jsx`
- Modify: `frontend/src/utils/api.js` (`orders: { propose: '/orders/propose', paper: '/orders/paper', cancelPaper: (id) => \`/orders/paper/${encodeURIComponent(id)}/cancel\` }`)
- Modify: `frontend/src/components/AnalysisCard.jsx`, `frontend/src/pages/Watchlist.jsx`, `frontend/src/pages/ScannerPage.jsx`, `frontend/src/pages/MyPortfolio.jsx`, `frontend/src/pages/Portfolio.jsx`

**Interfaces:**
- Consumes: `POST /orders/propose` (Task 3), `POST /chat/actions/{id}/confirm|cancel` (`endpoints.chat.confirm/cancel`), `GET /orders/paper`, `POST /orders/paper/{id}/cancel`, `GET /settings/preferences` → `broker_roles`.
- Produces: `<OrderTicket symbol side venue lastPrice onClose onDone />` default export.

- [ ] **Step 1: Build `OrderTicket.jsx`**

Modal: fixed overlay `z-[60]`, bottom sheet on phone / centred `max-w-md` on desktop, `role="dialog" aria-modal="true" aria-labelledby`, focus first control on open, Esc and backdrop close. Segmented controls reuse the `Tabs` styling with `className="static z-auto"` (as ScannerPage did). Mine disabled (with the spec's copy and `/settings?tab=accounts` link) when no `broker_roles` value is `"mine"`. States: `edit → review(card) → done(result)`; Review/Confirm/second tap/close-cancels exactly as the spec's Flow. Errors: `err.response.data.detail` inline, `role="alert"`.

- [ ] **Step 2: Wire the entry points per the spec's table**

Row buttons call `event.stopPropagation()`. MyPortfolio: equity rows only (`row.kind !== 'MF'`). Portfolio (Practice → Book): add the **Open orders** sheet (hidden when empty; Cancel per row; reload on `onDone` and every 60 s with `setInterval` cleared on unmount).

- [ ] **Step 3: Build and lint**

Run: `cd frontend && npm run build && npx eslint src/components/trading/OrderTicket.jsx src/components/AnalysisCard.jsx src/pages/Watchlist.jsx src/pages/ScannerPage.jsx src/pages/MyPortfolio.jsx src/pages/Portfolio.jsx`
Expected: build succeeds, 0 lint errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(orders): order ticket on stock page, watchlist, scanner, holdings and the practice book"
```
