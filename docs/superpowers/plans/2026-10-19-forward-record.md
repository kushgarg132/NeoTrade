# Forward record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every candidate from Picks, engine intraday entries, LONGTERM suggestions and news proposals is stored before its outcome, scored net vs NIFTY in the 16:00 pass, and labelled proven/unproven by one common rule shown across the app.

**Architecture:** New `backend/forward/` package: `store.py` (Mongo), `score.py` (pure scoring over the Picks daily-bar table + a pass step), `scorecard.py` (pure stats + rule + gate comparison). Writers are best-effort calls added to existing code paths. Admin API + Lab › Forward tab + a shared badge.

**Tech Stack:** Python 3.11 (prod image), pandas, FastAPI + Motor; React 19 (`node:test`).

**Spec:** `docs/superpowers/specs/2026-10-19-forward-record-design.md`

## Global Constraints

- Collection `forward_records`; `_id = "<source>:<name>:<symbol>:<YYYY-MM-DD>:<side>"`; `source` ∈ `picks | engine | suggestion | news`; `user_id = "system"` for Picks.
- Horizons: Picks = setup horizon; engine (INTRADAY) = 0; suggestion = proposal `max_hold_days` else 20; news = 5.
- Rule: `MIN_N = 100`, `MIN_T = 2.0`, `MAX_GAP = 0.05`; proven = `n >= MIN_N and mean_excess > 0 and t >= MIN_T and (gap is None or gap <= MAX_GAP)`.
- Net returns only via `lab/assumptions.py::round_trip_return` (10 bps + CNC charges). Void after 10 trading days past due with no bars.
- Writers and the scorer never raise into callers. The forward record never gates money; existing gates unchanged.
- Backtests and scans never write engine records.
- API and Lab › Forward page admin only.
- Backend gate: `docker build -q -t neotrade-verify backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify sh -c "python -m pytest -q backend/tests; lint-imports --config backend/.importlinter"` (Python 3.11: no PEP 701 nested-quote f-strings). Frontend: `cd frontend && node --test $(find src -name '*.test.js')` and `npm run build`.
- Each code change updates its `docs/wiki/*` section and `verified_at` in the same commit. Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A Picks pass where the forward insert fails still stores picks and scores them: T3 test with a failing store.
- A backtest run of an intraday strategy writes zero forward records: T3 test.
- A record decided the day before the NSE holiday 2026-10-20 with horizon 1 enters 2026-10-21 open: T2 test.
- The 16:00 pass continues to the post-close digest when the scorer raises: T2 test.
- Non-admin `GET /api/v1/forward/scorecard` → 403: T4 test.

---

## Wave 1 (parallel: Tasks 1, 2)

### Task 1: Store and scorecard

**Files:**
- Create: `backend/forward/__init__.py`, `backend/forward/store.py`, `backend/forward/scorecard.py`, `backend/tests/test_forward_store.py`, `backend/tests/test_forward_scorecard.py`
- Modify: `backend/server.py` (startup `ForwardStore(db).ensure_indexes()`, best effort like other stores), `backend/.importlinter` (add `backend.forward` to `domain-not-routers` sources)

**Interfaces:**
- Produces (`store.py`): `COLLECTION = "forward_records"`; `record_id(source, name, symbol, day: date, side) -> str`; `ForwardStore(db)` with `async ensure_indexes()`, `async record(*, source: str, name: str | None, user_id: str, symbol: str, side: str, decided_at: datetime, intraday: bool, ref_price: float | None, horizon_days: int, predicted: dict | None = None) -> bool` (False on duplicate or error, never raises; name None → `"unknown"`), `async due(now: datetime) -> list[dict]` (outcome None), `async set_outcome(record_id: str, outcome: dict, now: datetime)`, `async list(source=None, name=None, limit=200) -> list[dict]` (newest first), `async scored(source=None) -> list[dict]` (outcome set and no `void`).
- Produces (`scorecard.py`): `MIN_N, MIN_T, MAX_GAP`; `stats(records: list[dict]) -> dict` keys `n, mean_net, mean_excess, t, hit_rate, brier, calibration_gap` (`brier`/`gap` None without `predicted.p_up`; `t` None when n < 2 or zero spread); `label(s: dict) -> dict` → `{"label": "proven" | "unproven", "progress": min(n, MIN_N)}`; `async scorecard(db) -> list[dict]` rows `{source, name, **stats, **label, gate: bool | None, disagrees: bool | None}`. Gate lookups: picks → `forecast/picks.py::live_refusal(scored picks for that setup) is None`; engine/suggestion → name in `risk/paper_gate.py::proven_strategies(db, admin_id, {name}, account_size)` where `admin_id` is the first user with role `admin` (look up how other admin-scoped jobs find it, e.g. `builder/draft.py` `admin_id`) and `account_size` from that user's prefs; no admin → gate None; news → `datalayer/outcomes.py` theme weight > 1 with n ≥ 20 (read the stored theme weights the reactor uses). Any lookup error → gate None.

- [ ] **Step 1: Failing tests**

```python
# test_forward_scorecard.py
def rec(net, nifty, p=None):
    return {"outcome": {"net": net, "nifty": nifty, "excess": net - nifty, "won": net > 0},
            "predicted": {"p_up": p} if p is not None else None}

def test_rule_boundaries():
    base = {"mean_excess": 0.01, "t": 2.0, "calibration_gap": 0.05}
    assert label({**base, "n": 100})["label"] == "proven"
    assert label({**base, "n": 99})["label"] == "unproven"
    assert label({**base, "n": 100, "t": 1.99})["label"] == "unproven"
    assert label({**base, "n": 100, "calibration_gap": 0.051})["label"] == "unproven"
    assert label({**base, "n": 100, "calibration_gap": None})["label"] == "proven"
    assert label({**base, "n": 150})["progress"] == 100

def test_stats_with_and_without_predictions():
    s = stats([rec(0.02, 0.01, 0.6), rec(-0.01, 0.0, 0.6)])
    assert s["n"] == 2 and s["hit_rate"] == 0.5
    assert s["calibration_gap"] == pytest.approx(0.1)
    assert stats([rec(0.02, 0.01)])["brier"] is None
```

```python
# test_forward_store.py (repo's in-memory Mongo fake)
async def test_record_is_idempotent(db): first True, second same id False, one doc
async def test_record_failure_returns_false(broken_db): returns False, no raise
async def test_due_and_set_outcome(db): due lists unscored; after set_outcome it is gone; scored() excludes void
```

- [ ] **Step 2:** Run in image → FAIL.
- [ ] **Step 3:** Implement. `t = mean_excess / (std(excess, ddof=1) / sqrt(n))`. `calibration_gap = abs(mean(p_up) - hit_rate)`, `brier = mean((p_up - won)^2)` over records with `p_up`.
- [ ] **Step 4:** Suite + lint green.
- [ ] **Step 5:** Wiki `picks-and-signals.md` (new Files rows, Data: `forward_records`), `platform.md` (startup index, import rule). Commit `feat(forward): forward record store and scorecard rule`.

### Task 2: Scorer and the 16:00 pass step

**Files:**
- Create: `backend/forward/score.py`, `backend/tests/test_forward_score.py`
- Modify: `backend/scheduler.py:141-145` (after the Picks block, its own try/except and `system/jobs.py::mark(..., "forward", ...)`)

**Interfaces:**
- Consumes: `ForwardStore.due`, `ForwardStore.set_outcome` (Task 1, exact signatures above — code against them; tests use a fake store object with those two methods).
- Produces: `outcome(t: dict, record: dict) -> dict | None` (pure: `t` is the `forecast/picks.py::load` table with `open`/`close` frames incl. `bars.NIFTY`; returns `{entry_date, exit_date, net, nifty, excess, won}`, `{"void": "no bars"}` when ≥ 10 trading days past due and still unscorable, else None); `async score_due(db, now: datetime, t: dict | None = None, store=None) -> int` (loads `t` via `picks.load` when None; returns count scored).

- [ ] **Step 1: Failing tests** on a synthetic table (bdate_range incl. 2026-10-19..2026-10-23 minus 2026-10-20, a symbol `AAA` and NIFTY):
  - BUY, decided 2026-10-19 16:00 IST, horizon 1, not intraday → entry 2026-10-21 open, exit 2026-10-22 close; `net == round_trip_return(open, close)`; `nifty` over the same days.
  - intraday BUY with `ref_price` → entry = ref_price, exit = same-day close.
  - SELL → `net` equals the BUY formula with entry/exit swapped (short P&L), charges as CNC both legs.
  - Unknown symbol → None; same record evaluated 10 trading days after due → `{"void": "no bars"}`.
  - `score_due` with a fake store sets outcomes only for scorable records and returns the count.
  - scheduler: monkeypatch `forward.score.score_due` to raise; the daily pass still reaches `send_postclose` (use the existing scheduler test pattern).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (trading-day arithmetic on the table's index; `backend/core/market_calendar.py` for the void cutoff). **Step 4:** Suite green.
- [ ] **Step 5:** Wiki `data-ai-jobs.md` (16:00 pass step + `job:last:forward`), `picks-and-signals.md` Flows. Commit `feat(forward): score due candidates in the 16:00 pass`.

---

## Wave 2 (parallel: Tasks 3, 4)

### Task 3: Writers

**Files:**
- Modify: `backend/forecast/picks.py::run` (after the `picks` insert), `backend/suggestions/sink.py::SuggestionSink.__call__` (after `store.create`), `backend/engine/runner.py` (`size_intents` and `run` gain `forward: Optional[Callable[[Order, Intent, str], Awaitable[None]]] = None`; called for INTRADAY entries just before `orders.append(order)`), `backend/routers/trading.py::_launch_run` (pass a recorder bound to `ForwardStore`, `source="engine"`, the run's user)
- Test: `backend/tests/test_forward_writers.py`

**Interfaces:**
- Consumes: `ForwardStore.record` (Task 1).
- Produces: `backend/forward/store.py::engine_recorder(db, user_id) -> Callable` (the bound recorder `_launch_run` passes; records `name = order.strategy_name`, `side = order.side.value`, `ref_price` = the intent's reference/entry price, `intraday=True`, `horizon_days=0`).

- [ ] **Step 1: Failing tests:** Picks `run` with a fake db writes one `picks` forward record per new pick with `predicted = {p_up, median}`; a ForwardStore that fails → picks still inserted and scored. Sink: `source="news"` proposal → `news` record horizon 5, name = first theme from the proposal (fall back `"news"`); other source → `suggestion`, horizon = `max_hold_days` or 20; a sink call that does not create a suggestion (pending exists, not armed) writes nothing. Runner: a `run_backtest` of an intraday strategy over fixture bars writes 0 records (no recorder passed); `size_intents` with a recorder writes one record per INTRADAY entry and none for LONGTERM.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; every call wrapped so an exception logs and continues. **Step 4:** Suite + lint green.
- [ ] **Step 5:** Wiki `trading-engine.md` (runner `forward` hook, launcher), `picks-and-signals.md` (Picks + sink writers). Commit `feat(forward): record every candidate at decision time`.

### Task 4: API, Lab › Forward, badge

**Files:**
- Create: `backend/routers/forward.py`, `backend/tests/test_forward_api.py`, `frontend/src/pages/LabForward.jsx`, `frontend/src/components/ForwardBadge.jsx`, `frontend/src/utils/forward.js`, `frontend/src/utils/forward.test.js`
- Modify: `backend/server.py` (mount, admin), `frontend/src/App.jsx` (`/lab/forward` in `RequireAdmin`), `frontend/src/components/layout/sections.js` (`LAB_TABS` add Forward), `frontend/src/utils/routes.js` (`ROUTES`, `ADMIN_ROUTES`), `frontend/src/utils/api.js`; badge on `pages/Picks.jsx` (per setup), Lab strategy cards (`pages/Strategies.jsx`), Mine ideas (the component listing ideas per strategy), `pages/AiOverview.jsx` (per strategy)

**Interfaces:**
- Consumes: `scorecard(db)`, `ForwardStore.list` (Task 1).
- Produces: `GET /api/v1/forward/scorecard` → `{"rows": [...]}`; `GET /api/v1/forward/records?source=&name=&limit=` → `{"records": [...]}`; both `require_admin`. Frontend `badgeFor(rows, source, name) -> {text, tone} | null` (`"Proven"` / `"Unproven 37/100"`; null when no row), `useForward()` hook fetching the scorecard once per page (admin only; non-admin or error → empty rows, badge hidden).

- [ ] **Step 1: Failing tests:** API admin 200 rows with label fields; non-admin 403; records filter by source. Frontend `badgeFor`: proven row → "Proven"; n=37 → "Unproven 37/100"; missing → null.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. Lab › Forward table columns: source, name, n/100, mean excess %, t, hit rate %, calibration gap, label, gate, a "disagrees" marker; clicking a row lists its records (date, symbol, side, net %, NIFTY %). **Step 4:** Backend suite, node tests, build.
- [ ] **Step 5:** Wiki `platform.md` (endpoints), `frontend.md` (page map, badge); handbook page; `PRODUCT.md` (proven/unproven label); `docs/ROADMAP.md` step 4 status. Commit `feat(forward): scorecard API, Lab Forward tab and proven badge`.

---

## Merge and ship

- [ ] Push main before each wave (worktrees branch from origin/main). Merge in task order; gate on main after each wave.
- [ ] Final whole-branch review; one fix wave if needed.
- [ ] Deploy direct (`[skip ci]` on HEAD) outside 15:30-17:00 IST; after the next 16:00 pass check `forward_records` count by source and `job:last:forward`.
