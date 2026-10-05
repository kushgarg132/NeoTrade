# Portfolio Rebalance Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Rebalance tab that turns target weights (rule plus overrides, optional new money, ticked new names) into pre-filled order tickets, and one-tap AI verdict buttons on each holding row.

**Architecture:** Pure maths in `backend/portfolio/rebalance.py` (no I/O). `routers/portfolio.py` loads the snapshot, journal lots, prefs and candidate prices, then calls it. The frontend renders results and opens the existing `OrderTicket`, pre-filled.

**Tech Stack:** FastAPI, Motor, yfinance, pytest; React 19, vitest.

**Spec:** `docs/superpowers/specs/2026-10-05-portfolio-rebalance-design.md`

## Global Constraints
- Nothing places orders in bulk or without the user. Every trade opens `OrderTicket` with venue `paper` by default. Live keeps the second tap (AGENTS.md).
- Every read and write is scoped to `user.id`.
- AI candidates and `suggested` row actions appear only when `verdicts_visible_to(user)` is true.
- Defaults: `{"rule": "cap", "max_stock_pct": 15, "max_sector_pct": 30, "overrides": {}}`.
- Charges filter: drop a trade when `charges > 1%` of its value. Charges come from `calculate_indian_costs(..., product="CNC")`, which adds the DP charge on sells.
- Tax: lots held more than 365 days are long-term. `est_tax = 0.20 × short_gain + 0.125 × long_gain`, with each term floored at 0.
- Limits:
  - Candidates: at most 20.
  - Overrides: at most 100.
  - `POST /portfolio/rebalance`: 10 per minute per user via `backend/rate_limit.allow`, 429 above that.
- Universe: STOCK and ETF holdings with a price. Mutual funds and unpriced holdings go to `excluded`.
- Run tests: `cd backend/.. && python3 -m pytest -q -p no:cacheprovider`. Frontend: `npm run build` and `npx vitest run`.
- Commits end with `[skip ci]` only on the commit that will be HEAD at push (deploy mode: direct).

## Review Focus
1. A holding with quantity 0 or price 0 (delisted or suspended): it is excluded, with no ZeroDivisionError. Test in Task 1.
2. Overrides naming a symbol that isn't in the universe: they are ignored rather than taking weight. Test in Task 1.
3. Every name clipped by the caps, with nowhere for the freed weight to go: the leftover becomes cash and the loop ends. Test in Task 1.
4. A user with no journal trades: every sell has `unknown_qty == quantity` and `est_tax` is None. Test in Task 2.
5. The ticket opened from a row action must not keep the previous ticket's quantity. Pre-filling happens through props only. Test in Task 5 (util test).

---

### Task 1: Target maths (`target_weights`, `target_gaps`)

**Files:**
- Create: `backend/portfolio/rebalance.py`
- Test: `backend/tests/test_rebalance.py`

**Interfaces:**
- Produces:
  - `universe(holdings: list[dict]) -> tuple[list[dict], list[dict]]` returns `(names, excluded)`.
    - Each name is `{"symbol", "kind", "sector", "quantity", "price", "value"}`.
    - `price` is `last_price or close_price`.
  - `target_weights(names: list[dict], targets: dict, total: float) -> dict[str, float]`. Weights sum to ≤ 1.
  - `target_gaps(holdings: list[dict], targets: dict) -> tuple[dict[str, float], float, list[dict]]` returns `(gap_by_symbol, total, excluded)`, where `gap = target_weight − current_weight`. It uses no new money and no candidates.
  - `DEFAULT_TARGETS` (the dict in Global Constraints).

- [ ] **Step 1: Write the failing tests**

```python
def h(symbol, value, price=100.0, kind="STOCK", sector="IT"):
    return {"symbol": symbol, "kind": kind, "sector": sector, "quantity": value / price, "last_price": price, "close_price": price}

def test_equal_weight_splits_evenly():
    w = target_weights(universe([h("A", 600), h("B", 300), h("C", 100)])[0], {"rule": "equal", "overrides": {}}, 1000)
    assert w == pytest.approx({"A": 1/3, "B": 1/3, "C": 1/3})

def test_cap_trims_and_redistributes():
    names = universe([h("A", 500, sector="X"), h("B", 300, sector="Y"), h("C", 200, sector="Z")])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 40, "max_sector_pct": 100, "overrides": {}}, 1000)
    assert w["A"] == pytest.approx(0.40)
    assert w["B"] == pytest.approx(0.30 + 0.10 * 0.6) and w["C"] == pytest.approx(0.20 + 0.10 * 0.4)

def test_sector_cap_applies_and_etfs_are_exempt():
    names = universe([h("A", 400), h("B", 400), h("E", 200, kind="ETF", sector=None)])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 100, "max_sector_pct": 50, "overrides": {}}, 1000)
    assert w["A"] + w["B"] == pytest.approx(0.50) and w["E"] == pytest.approx(0.50)

def test_override_beats_rule_and_unknown_override_is_ignored():
    names = universe([h("A", 500), h("B", 500)])[0]
    w = target_weights(names, {"rule": "equal", "overrides": {"A": 20, "ZZZ": 50}}, 1000)
    assert w == pytest.approx({"A": 0.20, "B": 0.80})

def test_all_clipped_leaves_cash_and_terminates():
    names = universe([h("A", 500, sector="X"), h("B", 500, sector="X")])[0]
    w = target_weights(names, {"rule": "cap", "max_stock_pct": 30, "max_sector_pct": 100, "overrides": {}}, 1000)
    assert sum(w.values()) == pytest.approx(0.60)

def test_funds_unpriced_and_zero_quantity_are_excluded():
    rows = [h("A", 100), {**h("MF1", 100), "kind": "MF"}, {**h("U", 100), "last_price": None, "close_price": None}, {**h("Z", 100), "quantity": 0}]
    names, excluded = universe(rows)
    assert [n["symbol"] for n in names] == ["A"]
    assert {e["symbol"] for e in excluded} == {"MF1", "U", "Z"}

def test_target_gaps_are_weight_differences():
    gaps, total, _ = target_gaps([h("A", 750), h("B", 250)], {"rule": "equal", "overrides": {}})
    assert total == 1000 and gaps == pytest.approx({"A": -0.25, "B": 0.25})
```

- [ ] **Step 2: Run** `python3 -m pytest -q -p no:cacheprovider backend/tests/test_rebalance.py`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the three functions in `backend/portfolio/rebalance.py`**

`target_weights` algorithm (the tests don't fix it, so it is spelled out here):
1. Drop override symbols that aren't in `names`. `fixed = {s: pct/100}`, and `R = max(0, 1 − sum(fixed))`.
2. Free names are those not in `fixed`.
   - Under `equal`, each free name gets `R/n`.
   - Under `cap`, a free name's start weight is `value/total`. A name with value 0 (a candidate) starts at `R/n`. Start weights are then scaled so free names sum to `R`.
3. Run up to 10 passes:
   - Clip each free name to `max_stock_pct/100`.
   - For each sector (STOCK with a non-null sector) whose free-plus-fixed weight exceeds `max_sector_pct/100`, scale its free names down to fit.
   - Spread the weight freed this pass over the unclipped free names, in proportion to their weight.
   - Stop when nothing changes or no unclipped name is left.
   - `equal` skips the clipping entirely.

- [ ] **Step 4: Run the same command.** Expected: 7 passed.

- [ ] **Step 5: Commit** `feat(portfolio): rebalance target weights`

### Task 2: Trades, charges filter, tax (`plan_rebalance`)

**Files:**
- Modify: `backend/portfolio/rebalance.py`
- Test: `backend/tests/test_rebalance.py`

**Interfaces:**
- Consumes: Task 1 functions; `backend.engine.execution.costs.calculate_indian_costs`. Read its signature in `costs.py:40` and pass `product="CNC"`.
- Produces:
  - `plan_rebalance(holdings, candidates: list[dict], targets: dict, new_money: float, lots: dict[str, list[tuple[date, float, float]]], today: date) -> dict`. The output shape is exactly the spec's "Output" block, without `stale_since`, which the router adds.
  - `candidates` items look like `{"symbol", "price", "kind": "STOCK", "sector": None}` and enter the universe with quantity 0.
  - `sell_tax(quantity, price, lots, today) -> dict` returns `{"short_gain", "long_gain", "unknown_qty", "est_tax"}`.
  - `charges(side: str, quantity: float, price: float) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
TODAY = date(2026, 10, 5)

def test_new_money_used_before_any_sell():
    out = plan_rebalance([h("A", 60_000), h("B", 40_000)], [], {"rule": "equal", "overrides": {}}, 20_000, {}, TODAY)
    assert all(t["side"] == "BUY" for t in out["trades"]) and [t["symbol"] for t in out["trades"]] == ["B"]

def test_overweight_is_sold_to_fund_buys_sells_listed_first():
    out = plan_rebalance([h("A", 80_000), h("B", 20_000)], [], {"rule": "equal", "overrides": {}}, 0, {}, TODAY)
    assert [(t["symbol"], t["side"]) for t in out["trades"]] == [("A", "SELL"), ("B", "BUY")]
    assert out["trades"][0]["quantity"] == 300

def test_buys_scaled_when_cash_short():
    out = plan_rebalance([h("A", 10_000), h("B", 10_000)], [{"symbol": "C", "price": 100.0, "kind": "STOCK", "sector": None}],
                         {"rule": "equal", "overrides": {}}, 0, {}, TODAY)
    spent = sum(t["value"] + t["charges"] for t in out["trades"] if t["side"] == "BUY")
    got = sum(t["value"] - t["charges"] for t in out["trades"] if t["side"] == "SELL")
    assert spent <= got + 1e-6

def test_share_dearer_than_slot_is_skipped():
    out = plan_rebalance([h("A", 9_000), h("B", 1_000, price=5_000)], [], {"rule": "equal", "overrides": {}}, 0, {}, TODAY)
    assert {"symbol": "B", "reason": "one share costs more than its slot"} in out["skipped"]

def test_tiny_trade_dropped_for_charges():
    out = plan_rebalance([h("A", 5_010, price=1.0), h("B", 4_990, price=1.0)], [], {"rule": "equal", "overrides": {}}, 0, {}, TODAY)
    assert out["trades"] == [] and any(s["reason"] == "charges above 1% of the trade" for s in out["skipped"])

def test_sell_tax_splits_short_and_long_fifo():
    lots = [(date(2025, 1, 1), 10, 50.0), (date(2026, 6, 1), 10, 80.0)]
    t = sell_tax(15, 100.0, lots, TODAY)
    assert t["long_gain"] == pytest.approx(500) and t["short_gain"] == pytest.approx(100)
    assert t["unknown_qty"] == 0 and t["est_tax"] == pytest.approx(0.125 * 500 + 0.20 * 100)

def test_sell_tax_with_no_journal_is_unknown():
    t = sell_tax(5, 100.0, [], TODAY)
    assert t["unknown_qty"] == 5 and t["est_tax"] is None

def test_weight_after_never_exceeds_100():
    out = plan_rebalance([h("A", 70_000), h("B", 30_000)], [], DEFAULT_TARGETS, 5_000, {}, TODAY)
    assert sum(t["weight_after"] for t in out["trades"]) <= 100 + 1e-6
```

- [ ] **Step 2: Run.** Expected: FAIL (ImportError on `plan_rebalance`).
- [ ] **Step 3: Implement** following the spec's "Trades" and "Tax on sells" sections.
  - `est_tax` is None when `unknown_qty == quantity`.
  - A buy scaled down to 0 shares is dropped silently.
  - `weight_*` values are percentages (0–100) of `total`.
  - Sort: sells, then buys, each by value descending.
  - `cash_left = new_money + proceeds − buy spend − all charges`.
- [ ] **Step 4: Run.** Expected: 15 passed.
- [ ] **Step 5: Commit** `feat(portfolio): rebalance trades with charges filter and tax estimate`

### Task 3: Prefs, endpoints, row actions

**Files:**
- Modify:
  - `backend/prefs.py` (default `rebalance_targets` = `DEFAULT_TARGETS`)
  - `backend/routers/settings.py` (`PreferencesPatch.rebalance_targets: Optional[RebalanceTargets]`)
  - `backend/routers/portfolio.py`
- Test: `backend/tests/test_portfolio_rebalance_router.py` (follow the client/auth fixtures in `test_portfolio.py`)

**Interfaces:**
- Consumes: Task 1/2 functions; `scorecard.open_lots`; `JournalStore(db).list_trades(user_id)`; `rate_limit.allow(redis, key, limit, window_seconds)`; `verdicts_visible_to(user)`; the `watchlist` collection `{user_id, symbols}`; `suggestions` documents with `{"user_id", "status": "PENDING", "mode": "LONGTERM"}`.
- Produces:
  - `RebalanceTargets(BaseModel)`:
    - `rule: Literal["equal", "cap"]`
    - `max_stock_pct: float = Field(15, gt=0, le=100)`
    - `max_sector_pct: float = Field(30, gt=0, le=100)`
    - `overrides: dict[str, float]`: each value must satisfy `0 < v ≤ 100`, at most 100 keys, and the values may sum to at most 100. Otherwise 422.
  - `GET /portfolio/rebalance/candidates` returns `[{"symbol", "price", "source": "watchlist" | "ai"}]`. Prices come from one `yf.download` of `<SYM>.NS` closes in a thread; a symbol with no price is dropped.
  - `POST /portfolio/rebalance`, body `{"new_money": float ≥ 0, "candidates": list[str] (max 20), "targets": RebalanceTargets | None}`, returns the `plan_rebalance` output plus `stale_since`.
  - On `GET /portfolio`, each holding row gets `suggested`, built by `suggest(row, gap, total) -> dict | None` in `rebalance.py`:
    - SELL: `{"side": "SELL", "quantity", "price"}`
    - ADD: `{"side": "BUY", "quantity", "price"}`, or `{"at_target": True}`
    - A dropped trade: `{"skipped": reason}`
  - `present()` sets `suggested = None` on every row when verdicts are hidden.

- [ ] **Step 1: Write the failing tests**
  - `test_rebalance_needs_a_snapshot`: POST with no snapshot gives 409, detail `"Refresh your portfolio first"`.
  - `test_rebalance_reads_only_own_snapshot`: another user's snapshot exists, this user has none, so 409.
  - `test_rebalance_returns_trades_and_uses_saved_targets`: seed a snapshot and prefs `rule=equal`, then assert the response trades match `plan_rebalance` on the same rows.
  - `test_overrides_over_100_rejected`: POST with `targets.overrides={"A": 60, "B": 50}` gives 422.
  - `test_candidates_hide_ai_picks_when_verdicts_hidden`: a non-admin user with `portfolio_verdicts != "all"` gets only `source == "watchlist"`. Monkeypatch the price fetch.
  - `test_get_portfolio_adds_suggested_for_admin_and_nulls_for_others`:
    - Admin: SELL row gives `suggested.quantity == held`; ADD row under target gives `side == "BUY"`; HOLD gives None.
    - Non-admin: every `suggested` is None.
  - `test_rebalance_rate_limited`: monkeypatch `allow` to return False, giving 429.
- [ ] **Step 2: Run.** Expected: FAIL (404 routes / KeyError).
- [ ] **Step 3: Implement.**
  - Lots: `{s: open_lots(trades, s) for s in held symbols}`, filtered to brokers when `account != "all"` (mirror `get_portfolio`).
  - `today`: `SystemClock().now().astimezone(IST).date()`.
  - Register `/rebalance/candidates` before any path-param route.
- [ ] **Step 4: Run** the full backend suite. Expected: all pass (1220 + new).
- [ ] **Step 5: Commit** `feat(portfolio): rebalance endpoints, saved targets and AI row actions`

### Task 4: OrderTicket pre-fill

**Files:**
- Modify: `frontend/src/components/trading/OrderTicket.jsx:48-56`
- Create: `frontend/src/utils/ticket.js`, `frontend/src/utils/ticket.test.js`

**Interfaces:**
- Produces:
  - `OrderTicket` accepts optional `quantity` (number) and `limitPrice` (number).
    - The initial `quantity` state is `String(quantity ?? 1)`.
    - With `limitPrice`, `orderType` starts at `'LIMIT'` and the limit field shows `String(limitPrice)`.
  - `ticketFrom(row) -> null | {symbol, side, quantity, limitPrice, lastPrice}` in `utils/ticket.js`. It returns null unless `row.suggested?.side` is set. It works for holding rows (`row.suggested`) and rebalance trades (pass `{symbol, suggested: trade}`).

- [ ] **Step 1: Write the failing test** (`ticket.test.js`):

```js
it('builds a sell ticket from a suggestion', () => {
  expect(ticketFrom({ symbol: 'A', last_price: 10, suggested: { side: 'SELL', quantity: 12, price: 10 } }))
    .toEqual({ symbol: 'A', side: 'SELL', quantity: 12, limitPrice: 10, lastPrice: 10 });
});
it('returns null for at-target or skipped', () => {
  expect(ticketFrom({ symbol: 'A', suggested: { at_target: true } })).toBeNull();
  expect(ticketFrom({ symbol: 'A', suggested: null })).toBeNull();
});
```
- [ ] **Step 2: Run** `npx vitest run src/utils/ticket.test.js`. Expected: FAIL.
- [ ] **Step 3: Implement** `ticketFrom` and the two `OrderTicket` props. Leave the rest of the ticket untouched.
- [ ] **Step 4: Run** vitest and `npm run build`. Expected: both pass.
- [ ] **Step 5: Commit** `feat(ticket): pre-fill quantity and limit from a suggestion`

### Task 5: Rebalance tab and row action buttons

**Files:**
- Create: `frontend/src/components/portfolio/Rebalance.jsx`
- Modify: `frontend/src/pages/MyPortfolio.jsx` (TABS, `Verdict` / row rendering in `HoldingsList` and `HoldingsTable`), `frontend/src/utils/api.js` (`portfolio.rebalance: '/portfolio/rebalance'`, `portfolio.candidates: '/portfolio/rebalance/candidates'`)

**Interfaces:**
- Consumes: Task 3 endpoints, Task 4 `ticketFrom` and the `OrderTicket` props, the existing `onTrade` prop (opens the ticket with the given props).
- Produces: `<Rebalance snapshot={snapshot} prefs onTrade />`.

- [ ] **Step 1: Row actions.** When `ticketFrom(row)` is non-null, render a button labelled `` `${side === 'SELL' ? 'SELL' : 'BUY'} ${quantity} · ${formatCurrency(quantity * price)}` `` in place of the Verdict stamp. Its `onClick` is `() => onTrade(ticketFrom(row))`.
  - `suggested.at_target` shows doc-meta "at target".
  - `suggested.skipped` shows its reason.
  - The button's `e.stopPropagation()` keeps the row from expanding.
- [ ] **Step 2: Rebalance tab.** Add `{ id: 'rebalance', label: 'Rebalance' }` between Holdings and Mix. The component holds:
  - Rule radio (Equal / Cap) and two number fields under Cap.
  - An override field per holding, blank meaning none.
  - The "Add ₹" field.
  - Candidate checkboxes, loaded once from the candidates endpoint, with a source badge (`Watchlist` / `AI pick`).
  - **Calculate**: save `{rebalance_targets}` via `api.patch(endpoints.settings.preferences)`, then POST rebalance.
  - Results use the ScannerPage pattern: phone `<ul>` plus desktop `Statement`.
    - Columns: Scrip, Side, Qty, Value, Weight now → after, Tax (sells: `est_tax` or "unknown"), and a Trade button calling `onTrade(ticketFrom({symbol, suggested: trade}))`.
    - `skipped` and `excluded` are listed below with their reasons.
    - `stale_since` shows "Prices from the last close".
  - A 422 or 409 `detail` shows in the same `role="alert"` box as ScannerPage.
- [ ] **Step 3: Verify.**
  - `npm run build` passes.
  - Playwright on the Vercel preview (or a local `vite preview` against prod API) with a 10-minute token in `$SP/tok` (umask 077, deleted after use).
  - Open `/mine`, then the Rebalance tab, then Calculate. Take a screenshot at 390px.
  - Tap one Trade button and confirm the ticket shows the quantity and limit. Close it without confirming.
- [ ] **Step 4: Commit** `feat(portfolio): rebalance tab and one-tap AI row actions`

### Task 6: Deploy and verify
- [ ] Amend nothing pushed. Make the final commit's subject end with `[skip ci]`, then `git push`.
- [ ] Run `cd /home/ubuntu/deploys/NeoTrade && git pull --ff-only && docker compose build backend && docker compose up -d backend`, in the background.
- [ ] Check that `docker logs --since 2m neotrade-backend` has 0 Traceback lines.
- [ ] Check that `POST /portfolio/rebalance` with a fresh token returns 200 and that every trade quantity is an integer.
- [ ] Vercel builds the frontend on push; do not run `vercel deploy`. Check the production page after the build.
