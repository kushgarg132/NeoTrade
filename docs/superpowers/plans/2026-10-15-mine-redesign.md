# Mine Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Mine into the owner's account home: performance over time (XIRR vs NIFTY), one ranked "Needs you" list, a page per stock with the owner's own thesis, and an Indian tax view.

**Architecture:** New backend package `backend/mine/` (lots, history, tax, thesis, events, actions, stock) behind one router `routers/mine.py` at `/api/.../mine`. Two new daily writers: the 16:00 pass writes `mine_daily`; ingest gets a `corp_events` loop. Frontend: four Mine tabs (Overview, Holdings, Tax, Journal) + `/mine/stock/:symbol`; Today slims to a glance.

**Tech Stack:** FastAPI, Motor/MongoDB (mongomock_motor in tests), pytest; React 19 + Vite, Recharts 3, vitest for pure helpers.

**Spec:** `docs/superpowers/specs/2026-10-15-mine-redesign-design.md`

## Global Constraints

- Every stored doc carries `user_id`; every query filters on it. Nothing keyed on "the operator".
- "Mine" brokers = `brokers.roles.brokers_for(roles, "mine")`; **no roles set ⇒ every broker is mine** (same rule as `portfolio/service.py::mine_holdings`).
- Dates for lots, days and FY are **IST** dates (`backend.engine.session.IST`).
- Tax: STCG 20% (held ≤ 365 days), LTCG 12.5% above ₹1,25,000 a FY (held > 365 days). One home: `backend/mine/tax.py`.
- Verdict-bearing output (`verdict_worse`, `add` actions, verdicts on the stock page) only when `verdicts_visible` (`portfolio/digest.py::verdicts_visible`); otherwise mask as `portfolio.py::present` does.
- No new conviction scoring, no prompts, no new dependency (XIRR in stdlib).
- Copy: tax figures carry "Estimate, not tax advice". The concept is "Needs you"; ideas are "Ideas".
- Nothing places an order: actions open the existing `OrderTicket`.
- Frontend checks: `npm run build` plus `npx vitest run`; backend: `cd backend && python -m pytest`.
- Deploy mode: ask once before the first push (host CLAUDE.md). Commit after every task.

## Review Focus

1. **No journal history yet** (import not run): history starts at the first snapshot with `partial: true`; tax shows an "import your Upstox history" state, never ₹0 as if real. Test in Task 2 and Task 6.
2. **Split / bonus**: journal qty and broker qty differ by an integer ratio ≥ 2 → scale lots (qty × r, price ÷ r), not "unknown". Test in Task 1.
3. **Funds (`kind == "MF"`)** have no `daily_bars`: left out of the curve (flag `funds_excluded`), kept in the headline value. Test in Task 2.
4. **Action ids contain `:`** and must route and stay scoped: user B dismissing user A's id changes nothing for A. Test in Task 9.
5. **Trade near IST midnight**: a fill at 2026-03-31T19:00Z is 2026-04-01 IST and belongs to the next FY. Test in Task 6.

## Waves (parallel by default, each implementer in its own worktree)

| Wave | Tasks | Notes |
|---|---|---|
| 1 | 1 → 2 → 3 | one implementer, sequential (shared files). Deploy = spec phase M1 |
| 2 | 4, 5, 6 in parallel | no shared files except `routers/mine.py`: each adds its own endpoints at the end; merge in order |
| 3 | 7, 8 in parallel | 7 = `actions.py` + Today/Telegram; 8 = `stock.py` |
| 4 | 9 then 10, 11, 12 in parallel | 9 owns `App.jsx`, `sections.js`, `api.js`, `Layout.jsx` |
| 5 | 13, 14 | 14 last |

---

### Task 1: Lots — open, realised, reconciled

**Files:**
- Create: `backend/mine/__init__.py` (empty), `backend/mine/lots.py`
- Modify: `backend/portfolio/scorecard.py:46-61` (delete `open_lots`, import it from `backend.mine.lots`)
- Test: `backend/tests/test_mine_lots.py`

**Interfaces:**
- Produces:
  - `Lot = tuple[date, float, float]` (IST buy date, qty, price)
  - `open_lots(trades: list[dict], symbol: str) -> list[Lot]` (moved unchanged)
  - `realised(trades: list[dict], symbol: str) -> list[dict]`: one row per FIFO match `{symbol, buy_date, sell_date, qty, buy_price, sell_price, gain}` (dates IST)
  - `reconcile(lots: list[Lot], broker_qty: float) -> tuple[list[Lot], float]`: returns (lots, unknown_qty)
  - `mine_trades(db, user_id: str) -> list[dict]`: journal trades on the user's mine brokers (`JournalStore.list_trades` + `journal/accounts.py::filter_trades`, roles from `PrefsStore`)
- Trade dict shape (journal): `symbol, side ("BUY"/"SELL"), quantity, price, traded_at (aware UTC), broker`.

- [ ] **Step 1: Write failing tests**

```python
def test_realised_matches_oldest_first():
    rows = lots.realised([buy("A", 10, 100, D1), buy("A", 10, 120, D2), sell("A", 15, 150, D3)], "A")
    assert [(r["qty"], r["buy_price"]) for r in rows] == [(10, 100), (5, 120)]
    assert sum(r["gain"] for r in rows) == 10 * 50 + 5 * 30

def test_reconcile_journal_short_of_broker_is_unknown():
    assert lots.reconcile([(D1, 6, 100)], 10) == ([(D1, 6, 100)], 4)

def test_reconcile_journal_over_broker_drops_oldest():
    assert lots.reconcile([(D1, 5, 100), (D2, 5, 110)], 7) == ([(D1, 2, 100), (D2, 5, 110)], 0)

def test_reconcile_split_scales_lots():  # Review Focus 2
    assert lots.reconcile([(D1, 10, 500)], 50) == ([(D1, 50, 100)], 0)

def test_scorecard_still_uses_open_lots():
    from backend.portfolio import scorecard
    assert scorecard.open_lots is lots.open_lots

async def test_mine_trades_only_mine_brokers(db):  # roles {"upstox": "mine", "kite": "ai"}
    assert {t["broker"] for t in await lots.mine_trades(db, "alice")} == {"upstox"}
```

Note on "over broker drops oldest": it consumes from the oldest lot first, so `[(D1,5),(D2,5)]` → 7 keeps 2 of D1 and all of D2.

- [ ] **Step 2:** `cd backend && python -m pytest tests/test_mine_lots.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `backend/mine/lots.py`. Split rule in `reconcile`: if `broker_qty / journal_qty` is an integer r ≥ 2 within 1e-6, scale every lot (qty × r, price ÷ r) before any other rule.
- [ ] **Step 4:** Run `tests/test_mine_lots.py tests/test_scorecard.py tests/test_rebalance.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): lots — open, realised, reconciled with the broker`.

---

### Task 2: Daily history and XIRR

**Files:**
- Create: `backend/mine/history.py`
- Modify: `backend/scheduler.py` (after `daily_reviews`, in its own try/except: `await history.write_all(db, now)`), `backend/server.py:131` area (index `mine_daily` `(user_id, date)` unique)
- Test: `backend/tests/test_mine_history.py`

**Interfaces:**
- Consumes: Task 1 `mine_trades`, `open_lots`; `datalayer/bars.py::read`, `nifty_closes`; `portfolio/service.py::latest_snapshot`, `mine_holdings`.
- Produces:
  - `mine_daily` doc: `{user_id, date: "YYYY-MM-DD", value, invested, nifty_value, flow, by_symbol: {sym: {"qty": float, "value": float}}, partial: bool}`. `flow` = net rupees in that day (buys − sells); `nifty_value` = NIFTY units bought with each flow × that day's close; `invested` = running sum of flows.
  - `xirr(flows: list[tuple[date, float]]) -> Optional[float]`: annual rate as a fraction. Investor sign: money in negative, value out positive. Newton from 0.1, bisection fallback on [-0.99, 10]; None when no sign change or no convergence.
  - `async backfill(db, user_id: str, today: date) -> int` (rows written; idempotent upsert)
  - `async write_today(db, user_id: str, now: datetime) -> Optional[dict]`
  - `async write_all(db, now: datetime) -> int`: every user with a snapshot; first call per user with no rows runs `backfill`
  - `async series(db, user_id: str, since: Optional[date]) -> list[dict]`
  - `async returns(db, user_id: str, today: date, extra_flows: list[tuple[date, float]] = ()) -> dict`: `{xirr, nifty_xirr, from_date, partial, funds_excluded}`. `extra_flows` are positive cash-backs (dividends, Task 6) added to the user's flows only.

Backfill rules:
- Days = NIFTY trading days from the first trade (or the first snapshot if there are no trades).
- Qty per day comes from the trades. Value = Σ qty × close; a missing bar carries the previous close.
- Unknown-date gap: the earliest snapshot's broker qty above the journal qty enters as one lot at the snapshot's `avg_price`, on that snapshot's IST date, and sets `partial: true`.
- Funds are skipped and set `funds_excluded: true`.

- [ ] **Step 1: Write failing tests**

```python
def test_xirr_one_year_ten_percent():
    assert history.xirr([(date(2025,1,1), -1000), (date(2026,1,1), 1100)]) == pytest.approx(0.10, abs=1e-4)

def test_xirr_none_without_sign_change():
    assert history.xirr([(date(2025,1,1), -1000)]) is None
    assert history.xirr([(date(2025,1,1), -1000), (date(2025,6,1), -5)]) is None

async def test_backfill_values_and_nifty(db):  # BUY 10 A @100 on D1; A closes 100,110; NIFTY 1000,1100
    await history.backfill(db, "alice", D2)
    row = await db["mine_daily"].find_one({"user_id": "alice", "date": D2.isoformat()})
    assert (row["value"], row["invested"], row["nifty_value"]) == (1100, 1000, 1100)

async def test_backfill_missing_bar_carries_close(db): ...  # A has no bar on D2 → value uses D1 close

async def test_no_trades_starts_at_first_snapshot_partial(db):  # Review Focus 1
    await history.backfill(db, "bob", D3)
    rows = await history.series(db, "bob", None)
    assert rows[0]["date"] == SNAPSHOT_DAY.isoformat() and rows[0]["partial"]

async def test_funds_left_out_of_curve(db):  # Review Focus 3
    assert (await history.returns(db, "alice", D2))["funds_excluded"] is True

async def test_write_all_scoped_per_user(db):
    await history.write_all(db, NOW)
    assert await db["mine_daily"].count_documents({"user_id": {"$nin": ["alice", "bob"]}}) == 0
```

- [ ] **Step 2:** Run `tests/test_mine_history.py`. Expected: FAIL.
- [ ] **Step 3:** Implement `history.py`, then wire `scheduler.py` and the index.
- [ ] **Step 4:** Run `tests/test_mine_history.py tests/test_scheduler.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): daily value history, backfill and XIRR`.

---

### Task 3: Mine router — overview and history

**Files:**
- Create: `backend/routers/mine.py`
- Modify: `backend/server.py` (`app.include_router(mine_router.router, prefix=settings.API_PREFIX, tags=["Mine"], dependencies=[Depends(get_current_user)])`)
- Test: `backend/tests/test_mine_router.py`

**Interfaces:**
- Consumes: Task 2 `series`, `returns`; `portfolio/digest.py::pulse`; `latest_snapshot`.
- Produces:
  - `router = APIRouter(prefix="/mine")`
  - `GET /mine/history?range=1M|6M|1Y|ALL` → `{points: [{date, value, invested, nifty_value}], from_date, partial}`; anything else → 422
  - `GET /mine/overview` → `{headline: {value, day_change, day_change_pct, pnl, pnl_pct, xirr, nifty_xirr, as_of, holdings_as_of}, drivers: {month: {top, bottom}, all: {top, bottom}}, mix}`
    - `top` and `bottom` are each up to 3 of `{symbol, contribution}`.
    - Month contribution = `by_symbol[sym].value` today − at month start − the symbol's flows this month.
    - All-time contribution = pulse holding pnl.
    - `mix` = the latest snapshot's `concentration`, or null.
  - Later tasks append endpoints to this file and **must not reorder** existing ones.

- [ ] **Step 1: Write failing tests** with the FastAPI `TestClient`, dependency-overriding `get_current_user` and patching `backend.database.db.db` to mongomock, as in `tests/test_today.py`:
  - `test_history_range_filters` (1M returns only points within 31 days)
  - `test_history_bad_range_422`
  - `test_overview_drivers_month` (fixture with two symbols; asserts top[0].symbol and contribution value)
  - `test_overview_other_user_sees_nothing` (bob gets `headline: null`)
  - existing `tests/test_routes_require_auth.py` must still pass with the new routes
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the router and register it.
- [ ] **Step 4:** Run `tests/test_mine_router.py tests/test_routes_require_auth.py`, then the full suite in the background. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): /mine/overview and /mine/history`. **Wave 1 deploy point (M1)**: after deploy, the owner runs the Upstox import (Journal → import), then `history.backfill` runs on the next 16:00 pass, or by hand via `docker exec neotrade-backend python -c ...`.

---

### Task 4: Thesis store and endpoints

**Files:**
- Create: `backend/mine/thesis.py`
- Modify: `backend/routers/mine.py` (append), `backend/server.py` (unique index `holding_theses (user_id, symbol)`)
- Test: `backend/tests/test_mine_thesis.py` (not `test_thesis.py`, which belongs to `suggestions/thesis.py`)

**Interfaces:**
- Produces:
  - `class ThesisIn(BaseModel)`: `why: str = Field("", max_length=2000)`, `target: Optional[float] = Field(None, gt=0)`, `stop: Optional[float] = Field(None, gt=0)`, `review_by: Optional[date] = None`; validator: when both are set, `stop < target`
  - `class ThesisStore(db)`: `get(user_id, symbol) -> Optional[dict]`, `all(user_id) -> dict[str, dict]`, `put(user_id, symbol, body: ThesisIn) -> dict` (sets `updated_at`), `ensure_indexes()`
  - `SYMBOL = r"^[A-Z0-9&\-]{1,20}$"`; the router upper-cases the path symbol and answers 422 on a mismatch
  - `GET /mine/thesis/{symbol}` → thesis or `{}`; `PUT /mine/thesis/{symbol}` → saved doc (no `_id`)

- [ ] **Step 1: Failing tests:**
  - `test_put_then_get_roundtrip`
  - `test_stop_above_target_422`
  - `test_negative_price_422`
  - `test_why_too_long_422`
  - `test_bad_symbol_422`
  - `test_user_b_cannot_read_a`
  - `test_put_twice_updates_not_duplicates`
- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): holding thesis — why, target, stop, review date`.

---

### Task 5: Tax report

**Files:**
- Create: `backend/mine/tax.py`
- Modify: `backend/portfolio/rebalance.py:116-117` (import `LONG_TERM_DAYS, STCG_RATE, LTCG_RATE` from `backend.mine.tax`), `backend/routers/mine.py` (append `GET /mine/tax`)
- Test: `backend/tests/test_mine_tax.py`

**Interfaces:**
- Consumes: Task 1 `realised`, `open_lots`, `reconcile`, `mine_trades`; `rebalance.charges`.
- Produces:
  - Constants: `STCG_RATE = 0.20`, `LTCG_RATE = 0.125`, `LTCG_EXEMPTION = 125_000`, `LONG_TERM_DAYS = 365`, `GRANDFATHER_DATE = date(2018, 2, 1)` (comment: rates effective 2024-07-23)
  - `current_fy(today: date) -> int` (FY 2026 = 2026-04-01..2027-03-31); `fy_bounds(fy) -> tuple[date, date]`
  - `is_long(buy: date, sell: date) -> bool` = `(sell - buy).days > LONG_TERM_DAYS`
  - `est_tax(short_gain: float, long_gain: float) -> float`. Set-off: a short loss offsets short gains, then long gains; a long loss offsets only long gains. Then `STCG_RATE * short + LTCG_RATE * max(long - LTCG_EXEMPTION, 0)`.
  - `report(trades, held: dict[str, float], prices: dict[str, float], fy: int, today: date) -> dict` with keys:
    - `realised {short_gain, long_gain, exemption_used, exemption_left, charges, est_tax, rows}`
    - `unrealised [{symbol, buy_date, qty, price, last, gain, term, days_to_long}]`
    - `turning_long [{symbol, buy_date, qty, gain, days, saving}]`: within 60 days and gain > 0; `saving = (STCG_RATE - LTCG_RATE) * gain`
    - `harvest {loss: [{symbol, qty, loss, saving}], gain: [{symbol, qty, gain}]}`: the gain list fills `exemption_left`, largest long gains first
    - `unknown [{symbol, qty}]`, `pre_2018 [symbol]`, `has_history: bool`
  - `GET /mine/tax?fy=` (default `current_fy`); prices come from `service.quoted` over the latest snapshot

- [ ] **Step 1: Failing tests** (exact values):

```python
def test_day_365_is_short_366_is_long():
    assert not tax.is_long(date(2025,4,1), date(2026,4,1))   # 365 days
    assert tax.is_long(date(2025,4,1), date(2026,4,2))

def test_exemption_straddle():
    assert tax.est_tax(0, 200_000) == pytest.approx(9_375)

def test_set_off_order():
    # STCG 50k, STCL 20k, LTCG 150k, LTCL 10k → short 30k, long 140k
    assert tax.est_tax(50_000 - 20_000, 150_000 - 10_000) == pytest.approx(6_000 + 1_875)

def test_short_loss_spills_into_long():
    assert tax.est_tax(-30_000, 200_000) == pytest.approx(0.125 * (170_000 - 125_000))

def test_ist_midnight_fill_lands_in_next_fy():  # Review Focus 5
    r = tax.report([buy("A", 1, 100, utc(2025,1,1)), sell("A", 1, 200, datetime(2026,3,31,19,0,tzinfo=timezone.utc))], {}, {}, 2026, date(2026,4,2))
    assert r["realised"]["long_gain"] == 100

def test_unknown_qty_excluded_and_listed(): ...

def test_no_history_flag():  # Review Focus 1
    assert tax.report([], {"A": 10}, {"A": 100}, 2026, date(2026,10,15))["has_history"] is False

def test_turning_long_saving(): ...  # gain 10k, 20 days left → saving 750

def test_rebalance_uses_same_rates():
    from backend.portfolio import rebalance
    assert rebalance.STCG_RATE is tax.STCG_RATE
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run `test_mine_tax.py test_rebalance.py test_portfolio_rebalance_router.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): FY tax report — STCG/LTCG, exemption, harvest, turning long-term`.

---

### Task 6: Corporate events and dividends

**Files:**
- Create: `backend/mine/events.py`
- Modify: `backend/datalayer/worker.py::_loops` (add `Loop("corp_events", 6 * 3600, events.loop)`), `backend/routers/mine.py` overview (pass dividends as `extra_flows` to `returns`)
- Test: `backend/tests/test_mine_events.py`

**Interfaces:**
- Produces:
  - `corporate_events` doc: `{symbol, kind: "results"|"ex_dividend", date: "YYYY-MM-DD", amount: Optional[float], source: "yfinance", fetched_at}`; unique `(symbol, kind, date)`. Market-wide reference data, so no `user_id` (like `instruments`).
  - `_fetch_sync(ticker: str) -> list[dict]`: yfinance `Ticker.calendar` (Earnings Date, Ex-Dividend Date) plus `Ticker.dividends` (last 3 years). The only network call; tests patch it.
  - `async refresh(db, symbols: set[str], today: date) -> int`: skips a symbol already fetched today (`corporate_events_meta {symbol, checked}`)
  - `async loop(db, redis, now=None) -> None`: the union of every user's `mine_holdings`
  - `async upcoming(db, symbols, today, days: int) -> list[dict]`
  - `async dividends_received(db, trades: list[dict], symbol: str, until: date) -> list[dict]`: `{date, per_share, qty, amount}`, qty held on the ex-date from Task 1 lots
- [ ] **Step 1: Failing tests:**
  - `test_refresh_once_a_day` (second call same day fetches 0)
  - `test_upcoming_window` (7 days includes day 7, excludes day 8)
  - `test_dividends_use_qty_on_ex_date` (bought 10 before, 5 more after → amount uses 10)
  - `test_fetch_failure_skips_symbol` (`_fetch_sync` raises → refresh logs, continues, returns count of the others)
  - `test_worker_registers_corp_events`
- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run with `test_datalayer_worker.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): results and dividend dates, dividends received`.

---

### Task 7: Needs you — actions, alerts, Today and Telegram

**Files:**
- Create: `backend/mine/actions.py`
- Modify:
  - `backend/routers/mine.py`: `GET /mine/actions`, `POST /mine/actions/{action_id:path}/dismiss`, `.../snooze`
  - `backend/routers/today.py`:
    - `_needs_you` drops the `exit`, `verdict` and `proposal` items
    - `today()` adds `"mine_actions": top3` and `"mine_actions_total": n`
    - review link `/mine/trades` → `/mine/journal`
  - `backend/engine/autorun.py:299` area: after `check_exits`, `alerts = await actions.level_alerts(db, redis, user_id, now)`; if any, `notify(db, user_id, actions.levels_text(alerts))`
  - `backend/portfolio/digest.py`: `premarket_text` and `postclose_text` take `actions: list[dict]` and add up to 3 lines; `send_*` pass `await actions.build(...)`
- Test: `backend/tests/test_mine_actions.py`; update `tests/test_today.py` and `tests/test_portfolio_digest.py`

**Interfaces:**
- Consumes:
  - Task 4 `ThesisStore.all`
  - Task 5 `report` (for `turning_long` and `harvest`)
  - Task 6 `upcoming`
  - `digest.pulse`, `digest.headlines_for`, `digest.verdicts_visible`
  - `rules.worsened`, `routers/today.py::_ideas`
  - open alerted trades in `mine_book(user_id)` (the exit query today's `_needs_you` uses)
- Produces:
  - `RANK = {"stop_hit": 10, "idea_exit": 15, "target_hit": 20, "verdict_worse": 30, "bad_news": 40, "idea": 45, "review_due": 50, "results_soon": 60, "overweight": 70, "ltcg_soon": 80, "harvest": 85, "ex_dividend": 90, "add": 95}`. `idea_exit` is today's Today `exit` item, moved here.
  - Action dict: `{id, kind, symbol, title, detail, rank, at, action: {type: "ticket"|"stock"|"tax"|"rebalance"|"idea"|"none", ...}}`
    - `ticket` carries `{side, quantity, price}`; `idea` carries `{suggestion_id}`
    - `id = f"{kind}:{symbol}:{key}"`. Keys: `stop_hit`/`target_hit` = the level; `verdict_worse` = `"{from}>{to}"`; `results_soon`/`ex_dividend` = the event date; `idea` = the suggestion id; `bad_news` = the url; `review_due` = the date; others = the IST date.
  - `async build(db, user_id: str, now: datetime, show_verdicts: bool) -> list[dict]`: sorted by `(rank, -at)`. Drops ids dismissed or snoozed (`until > now`) in `mine_action_state`. Drops `verdict_worse`/`add` when `not show_verdicts`. `harvest` only in Jan–Mar IST.
  - `async dismiss(db, user_id, action_id)`; `async snooze(db, user_id, action_id, now, days=7)`
  - `async level_alerts(db, redis, user_id, now) -> list[dict]`: `stop_hit`/`target_hit` from ingest marks (`suggestions/exits.py::mark_prices`). Once per id via redis `SET mine:alert:{user_id}:{id} NX EX 2592000`.
  - `levels_text(alerts: list[dict]) -> str`
- [ ] **Step 1: Failing tests:**
  - `test_rank_order` (fixture triggers stop_hit, bad_news, ex_dividend → that order)
  - `test_ids_stable_across_builds`
  - `test_dismiss_hides_until_new_key` (dismiss a verdict_worse HOLD>SELL; a later SELL>... change yields a new id that shows)
  - `test_snooze_expires_after_7_days`
  - `test_verdict_items_hidden_without_visibility`
  - `test_harvest_only_jan_to_mar`
  - `test_level_alert_once` (two calls, one alert)
  - `test_dismiss_other_users_id_is_scoped` (Review Focus 4: bob dismisses alice's id via `POST /mine/actions/stop_hit:A:90/dismiss`; alice's build still has it)
  - `test_today_mine_actions_top3_and_no_duplicate_holding_items`
  - `test_postclose_text_lists_top_actions`
- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run `test_mine_actions.py test_today.py test_portfolio_digest.py test_autorun.py`, then the full suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): Needs you list, level alerts, Today and Telegram read it`.

---

### Task 8: Stock detail endpoint

**Files:**
- Create: `backend/mine/stock.py`
- Modify: `backend/routers/mine.py` (append `GET /mine/stock/{symbol}`), `backend/routers/portfolio.py` (extract `mask_row(row) -> dict` out of `present` for reuse, no behaviour change)
- Test: `backend/tests/test_mine_stock.py`

**Interfaces:**
- Consumes: Tasks 1, 4, 5 (`is_long`, rates), 6 (`upcoming`, `dividends_received`), 2 (`xirr`); `service.quoted`; `bars.read`; `mask_row`.
- Produces: `async detail(db, user_id, symbol, now, show_verdicts) -> dict` with keys:
  - `position {qty, avg_price, value, pnl, pnl_pct, xirr, held_since, sold: bool}`
  - `lots [{buy_date, qty, price, days_to_long, gain, est_tax}]`, `unknown_qty`
  - `thesis`
  - `verdict {current, reasons, note, history: [{date, verdict}]}`. History is one entry per change across `portfolio_snapshots`, oldest first.
  - `events`, `dividends`
  - `news`: up to 10 `news_items` with `impacts.target == symbol`, newest first
  - `closes [{date, close}]` (1 year), `trades [{date, side, qty, price}]`

  A symbol that is neither held nor traded returns 404.
- [ ] **Step 1: Failing tests:**
  - `test_held_position_and_lots`
  - `test_sold_symbol_still_opens` (`sold: True`, trades present)
  - `test_unknown_symbol_404`
  - `test_verdict_history_only_changes` (snapshots HOLD, HOLD, SELL → 2 entries)
  - `test_verdict_masked_without_visibility` (SELL → REVIEW, note kept)
  - `test_portfolio_present_unchanged` (existing `test_portfolio.py` passes)
- [ ] **Step 2–4:** Run → FAIL → implement → PASS (plus `test_portfolio.py`).
- [ ] **Step 5:** Commit `feat(mine): stock detail — position, lots, thesis, verdict history, events`.

---

### Task 9: Frontend shell, nav and Overview

**Files:**
- Create: `frontend/src/pages/MineOverview.jsx`, `frontend/src/components/mine/ValueCurve.jsx`, `frontend/src/components/mine/NeedsYou.jsx`, `frontend/src/utils/mine.js`, `frontend/src/utils/mine.test.js`
- Modify:
  - `frontend/src/App.jsx:100-104`: routes per the spec table; `/mine/ideas` → `/mine`, `/mine/trades` → `/mine/journal`, `/mine/habits` → `/mine/journal?tab=habits`
  - `/mine/holdings`, `/mine/tax`, `/mine/stock/:symbol`, `/mine/journal` routes, with temporary elements as below
  - `frontend/src/components/layout/sections.js`: Mine `path: '/mine'`; `MINE_TABS = [{to:'/mine',label:'Overview',end:true,counter:true},{to:'/mine/holdings',label:'Holdings'},{to:'/mine/tax',label:'Tax'},{to:'/mine/journal',label:'Journal'}]`
  - `frontend/src/utils/api.js`: `mine: { overview, history: (range) => ..., actions, dismiss: (id) => \`/mine/actions/${encodeURIComponent(id)}/dismiss\`, snooze, stock: (s), thesis: (s), tax: (fy) }`
  - `frontend/src/components/Layout.jsx:29-33`: the pending count = `GET /mine/actions` length (context name kept)
- Test: `frontend/src/utils/mine.test.js`

**Interfaces:**
- Produces (in `utils/mine.js`, used by Tasks 10–13):
  - `rangeLabel`, `RANGES = ['1M','6M','1Y','ALL']`
  - `actionTarget(action) -> { to?: string, ticket?: {symbol, side, quantity, limitPrice} }`
    - `stock` → `/mine/stock/:symbol`; `tax` → `/mine/tax`; `rebalance` → `/mine/holdings?plan=1`
    - `ticket` → ticket props; `idea` → `{ to: '/mine', idea: id }`
  - `targetProgress(avg, last, target) -> number|null`: 0..1 clamped, null without a target
  - `sortHoldings(rows, key: 'weight'|'day'|'gain'|'verdict') -> rows`
  - `formatXirr(x) -> string`: `null` → `'—'`, `0.1234` → `'12.3%'`
  - `NeedsYou` props: `{ actions, onChanged, limit?: number }`. Each row has dismiss and snooze, and opens `OrderTicket` for tickets. `idea` rows render `SuggestionRecord` approve/decline (the existing `suggestions.approveLive`/`reject`).
- Until Tasks 10–12 land, `/mine/holdings` keeps the old `MyPortfolio`, `/mine/tax` renders an `Empty`, and `/mine/journal` keeps `Journal view="trades"`. Each later task replaces its own route element only.

- [ ] **Step 1: Failing vitest:**
  - `actionTarget` maps every `type`
  - `targetProgress(100, 150, 200) === 0.5`, `targetProgress(100, 250, 200) === 1`, `targetProgress(100, 90, null) === null`
  - `formatXirr(null) === '—'`
  - `sortHoldings` by verdict puts SELL first
- [ ] **Step 2:** `cd frontend && npx vitest run src/utils/mine.test.js`. Expected: FAIL.
- [ ] **Step 3:** Implement the helpers, then `MineOverview` in spec order:
  - headline
  - `ValueCurve` (Recharts `LineChart`, three series, range chips; load the `dataviz` skill first)
  - `WaitingCards`
  - `NeedsYou` (empty state: "You're clear.")
  - drivers (month/all toggle)
  - Mix (move `Concentration` out of `MyPortfolio.jsx` into `components/mine/Mix.jsx`)

  Phone first (375px). Use `Sheet`/`Money`/`Stamp` from `components/doc/Doc`.
- [ ] **Step 4:** `npx vitest run && npm run build`. Expected: both PASS.
- [ ] **Step 5:** Commit `feat(mine): Overview — value curve, Needs you, drivers, mix; new Mine nav`.

---

### Task 10: Holdings list

**Files:**
- Create: `frontend/src/pages/MineHoldings.jsx`
- Modify: `frontend/src/App.jsx` (the `/mine/holdings` element only)
- Reuse: `components/portfolio/Rebalance.jsx`, `NewsChip`, `useSymbolNews`, the `utils/mine.js` helpers

**Interfaces:** Consumes:
- `GET /portfolio?account=mine&live=true`, using the existing 5s poll logic from `MyPortfolio.jsx:442-467`, moved over.
- `GET /mine/actions`, for the "Needs you" filter.
- Thesis targets, which arrive inside the portfolio rows. **Add** `thesis_target` to each holding in `routers/portfolio.py::get` from `ThesisStore.all` (one backend line; test in `test_portfolio.py`: `test_rows_carry_thesis_target`).

- [ ] **Step 1:** Write the backend test `test_rows_carry_thesis_target`. Run it. Expected: FAIL.
- [ ] **Step 2:** Add the field. Run it. Expected: PASS.
- [ ] **Step 3:** Build the page:
  - Sort chips: Weight (default), Day, Gain, Verdict. Filter chips: Needs you, Stocks, Funds. "Needs you" = symbols present in `GET /mine/actions`.
  - Phone rows: symbol, weight, value, day %, total %, verdict stamp, `targetProgress` bar. Desktop: a `Statement` with the same columns.
  - Row → `navigate('/mine/stock/:symbol')`.
  - "Plan new money" opens `Rebalance` in a sheet; `?plan=1` opens it on load.
  - Broker-logged-out "as of" line kept.
- [ ] **Step 4:** `npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(mine): Holdings — sortable list, target progress, stock pages`.

---

### Task 11: Stock page and thesis editor

**Files:**
- Create: `frontend/src/pages/MineStock.jsx`, `frontend/src/components/mine/ThesisEditor.jsx`
- Modify: `frontend/src/App.jsx` (the `/mine/stock/:symbol` element only)

**Interfaces:** Consumes `GET /mine/stock/{symbol}` (Task 8 shape) and `PUT /mine/thesis/{symbol}` (Task 4). `ThesisEditor` props: `{ symbol, thesis, onSaved }`. The server's 422 `detail` is shown inline.

- [ ] **Step 1:** Build the sections in spec order: Position + lots table, chart, thesis, verdict + history, coming up, dividends, news, actions.
  - Chart: Recharts `ComposedChart` over `closes`, with buy/sell `ReferenceDot`s from `trades` and target/stop `ReferenceLine`s. Don't reuse `TradingChart`, which takes intraday candles.
  - Verdict reasons: reuse the `REASONS` map, moved from `MyPortfolio.jsx` to `utils/mine.js`.
  - Sold → banner "Sold"; position figures hidden.
  - 404 → `Empty` "Not in your account".
- [ ] **Step 2:** `npm run build`. Expected: PASS.
- [ ] **Step 3:** Commit `feat(mine): stock page — lots, chart with your trades, thesis, verdict history`.

---

### Task 12: Tax page

**Files:**
- Create: `frontend/src/pages/MineTax.jsx`
- Modify: `frontend/src/App.jsx` (the `/mine/tax` element only)

**Interfaces:** Consumes `GET /mine/tax?fy=` (Task 5 shape).

- [ ] **Step 1:** Build the page:
  - FY select: current and the previous 3.
  - Sheets: Realised this FY (with an exemption used/left bar), Unrealised by lot, Turning long-term soon, Before 31 March (loss + gain harvest).
  - `has_history === false` → `Empty` "Import your Upstox history to see tax" with a button calling `journal.importUpstox`.
  - `unknown` and `pre_2018` notes.
  - Footer copy, verbatim: "Estimate, not tax advice. Not covered: pre-2018 grandfathered cost, F&O and intraday income, set-off against other income."
- [ ] **Step 2:** `npm run build`. Expected: PASS.
- [ ] **Step 3:** Commit `feat(mine): Tax page`.

---

### Task 13: Today glance and Journal tabs

**Files:**
- Modify: `frontend/src/pages/Today.jsx` (replace `Pulse` at lines ~146-215, and drop the `exit`/`verdict`/`proposal` renderers in "Do today"), `frontend/src/pages/Journal.jsx` (`view` prop → inner `Tabs` Trades · Habits via `useTab`), `frontend/src/App.jsx` (the `/mine/journal` element → `<Journal lockedAccount="mine" />`)

**Interfaces:** Consumes `today.pulse`, `today.mine_actions`, `today.mine_actions_total` (Task 7) and `NeedsYou` with `limit={3}` (Task 9).

- [ ] **Step 1:** Today "Your account" becomes:
  - one line: value · today · overall
  - then `NeedsYou limit={3}`
  - then a link `See all ${mine_actions_total} in Mine ›` → `/mine`
  - Movers move to the Overview drivers (they are not shown on Today any more).
- [ ] **Step 2:** Journal: `?tab=habits` opens Habits.
- [ ] **Step 3:** `npx vitest run && npm run build`. Expected: PASS.
- [ ] **Step 4:** Commit `feat(today): glance + top 3 from Needs you; journal holds trades and habits`.

---

### Task 14: Cuts, redirects, docs

**Files:**
- Delete: `frontend/src/pages/MyPortfolio.jsx` (only after confirming `grep -rn "MyPortfolio" frontend/src` hits nothing but `App.jsx`, which now uses `MineHoldings`), `frontend/src/pages/Decisions.jsx`, `PlanGroups`/Review code with them
- Modify:
  - `frontend/src/App.jsx`: drop the dead imports
  - `PRODUCT.md`: Surfaces table rows for Mine, Today
  - `frontend/src/handbook/*.md`: the Mine pages and the `backend/mine/` modules, with `file::symbol` anchors
  - `docs/ROADMAP.md`: add a Phase 20 row "Mine redesign" with status and the spec/plan paths
  - `backend/routers/portfolio.py`: keep `/portfolio/refresh` (the daily pass and chat use it); the "Analyse now" button is gone from the UI only
- Test: `frontend/src/utils/handbook.test.js` (anchors resolve)

- [ ] **Step 1:** `grep -rn "Decisions\|MyPortfolio\|/mine/ideas\|/mine/trades\|/mine/habits" frontend/src backend --include=*.js* --include=*.py --include=*.md`. Every hit is either a redirect in `App.jsx` or gets updated.
- [ ] **Step 2:** Delete and update.
- [ ] **Step 3:** `npx vitest run && npm run build`, and `cd backend && python -m pytest` in the background. Expected: all PASS.
- [ ] **Step 4:** Commit `chore(mine): cut Plan/Review/Ideas pages; docs and handbook for the new Mine`.
- [ ] **Step 5:** Deploy per the session's deploy mode. Prod checks:
  - `/health` 200
  - `GET /mine/overview` 200 with `headline.xirr`
  - `GET /mine/actions` under 1s
  - after 16:00 IST, `mine_daily` has today's row
  - `corporate_events` populated for held symbols within a day
