# User Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any user composes a block strategy on Practice › Strategies; it is backtested through the builder's checks and, if it passes, trades only on that user's paper book.

**Architecture:** `built_strategies` docs gain `owner_id` (`None` = the AI's global drafts). One choke point scopes them: `build_default_strategies(..., user_id=...)` loads global + that user's active specs. The builder gains a one-draft test mode (`python -m backend.builder --test <slug>`) that the new submit endpoint spawns; sizing and the overfitting trial count follow the draft's owner.

**Tech Stack:** Python / FastAPI / Motor; React 19 + Vite. Tests: from the repo root `docker run --rm -v "$PWD":/app -w /app --entrypoint sh neotrade-backend -c "python -m pytest -q -p no:cacheprovider <path>"`; frontend `cd frontend && npm run build` (and `npx vitest run`).

**Spec:** `docs/superpowers/specs/2026-10-07-user-strategies-design.md`

## Global Constraints

- A user's strategy loads, lists and trades only for its owner; `owner_id = None` drafts stay global. `user_id=None` in `build_default_strategies` loads global ones only.
- No user input or model output executes as code: every spec goes through `builder/validate.py::validate_spec`.
- Checks unchanged: `passes_gate` AND last-90-day net > 0 AND Deflated Sharpe ≥ 0.95; the trial count is per owner (`store.trial_sharpes(db, owner_id)`).
- Limits per user: 3 submissions (incl. re-tests) per IST day; one `testing` at a time; 5 `active`. Messages: "A strategy of yours is still being tested.", "Retire one first.", "3 strategies a day: try again tomorrow."
- Sizing for a user's draft: the owner's `account_size`, `max_exposure`, `per_trade_cap`; history: the admin's Upstox year (`risk/gate_backtest.py::intraday_history`).
- `backend/strategies/` stays I/O-free. Commits end the subject with ` [skip ci]` plus the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` trailer.

## Review Focus

1. Another user's slug in retire/retest/listing → 404 / absent, never a leak of its spec. → Task 3 `test_other_users_strategy_is_invisible_and_untouchable`.
2. Submitting while the weekly AI run holds `builder:lock` → the one-draft test must not wait on or break that lock (separate per-slug lock). → Task 2 `test_test_one_runs_while_the_weekly_lock_is_held`.
3. The weekly AI run meets a user's draft still `testing` → tests it with the owner's sizing and owner trial count, not the admin's. → Task 2 `test_weekly_run_retests_a_users_waiting_draft_with_owner_sizing`.
4. The 5-active cap: the AI's `_make_room` must count and retire only AI drafts, never a user's. → Task 1 `test_make_room_ignores_user_strategies`.
5. A user deleted or with no prefs doc → sizing falls back to `prefs.DEFAULTS`, never a crash. → Task 2 `test_owner_without_prefs_uses_defaults`.

---

### Task 1: Owner scoping in store and registry

**Files:**
- Modify: `backend/builder/store.py`, `backend/strategies/registry.py`, `backend/builder/draft.py` (`_make_room`, `_run` trial count), callers that act for a user: `backend/routers/trading.py::launch_run`, `backend/learning/library.py::catalog` (its `_strategies` gets `user_id`), `backend/routers/settings.py` (strategy list + promotion), `backend/chat/tools.py` (strategy-name tool), `backend/plan/replay.py`
- Test: `backend/tests/test_user_strategies_scope.py`

**Interfaces:**
- Produces:
  - Docs carry `owner_id: str | None` (absent = None).
  - `store.trial_sharpes(db, owner_id: str | None = None) -> list[float]` (filter `owner_id` equality; None matches absent).
  - `store.visible(db, user_id: str) -> list[dict]`: drafts with `owner_id` None/absent or == user_id, newest first, no `_id`.
  - `build_default_strategies(..., user_id: str | None = None)`: built docs from `active()` with `doc.get("owner_id") in (None, user_id)`.
  - `draft._make_room(db)` counts/retires only `owner_id` None actives.

- [ ] **Step 1: Failing tests**

```python
def test_registry_loads_global_plus_own_only():
    set_active([{"slug": "g", "spec": EX}, {"slug": "a", "spec": EX, "owner_id": "A"}, {"slug": "b", "spec": EX, "owner_id": "B"}])
    names = lambda uid: {s.spec.name for s in build_default_strategies(universe=["X"], user_id=uid) if s.spec.name.startswith("built:")}
    assert names("A") == {"built:g", "built:a"} and names(None) == {"built:g"}

async def test_trial_sharpes_per_owner(): ...       # AI 2 tested, A 1 tested -> lens 2 and 1
async def test_visible_is_global_plus_own(): ...
async def test_catalog_lists_own_built_only(): ...   # catalog(db, "B", []) has no built:a
async def test_make_room_ignores_user_strategies(): ... # 5 user actives + 4 AI actives -> AI pass retires nothing
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `feat(strategies): built strategies scoped by owner`.

### Task 2: One-draft test mode, owner sizing

**Files:**
- Modify: `backend/builder/draft.py`, `backend/builder/__main__.py`, `backend/risk/gate_backtest.py`
- Test: `backend/tests/test_builder_draft.py` (append)

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `gate_backtest.backtest_account(db, user_id: str | None = None) -> dict`: that user's prefs (or the admin's when None; `prefs.DEFAULTS` when missing).
  - `draft._history(db, redis)` returns `(backtest, kwargs)` where `backtest(strategy, start, end, account: dict)`; `_test(db, doc, backtest, kwargs, now)` sizes with `await backtest_account(db, doc.get("owner_id"))` and counts `store.trial_sharpes(db, doc.get("owner_id"))`.
  - `async def test_one(db, redis, slug: str, now: datetime, backtest=None) -> dict`: Redis lock `builder:test:<slug>` (SET NX, 1 h TTL, released in finally); loads the doc; must be `testing`; no LLM call; no history → set verdict "waiting for market history", stays `testing`; backtest exception → stays `testing` with verdict "test failed: <ExceptionName>"; else `set_status` with `_test`'s result. Returns `{"slug", "status", "verdict"}`. A user draft that passes does NOT call `_make_room` (the cap is enforced at submit).
  - `async def spawn_test(slug: str) -> None`: like `spawn()` with args `-m backend.builder --test <slug>`.
  - `__main__`: `--test <slug>` → `test_one`, else the weekly `run`.
  - Weekly `_run` keeps testing every waiting draft (AI and user), each sized and counted by its owner.

- [ ] **Step 1: Failing tests** `test_test_one_tests_only_that_draft_without_llm`, `test_test_one_runs_while_the_weekly_lock_is_held` (`builder:lock` set → still tests), `test_test_one_uses_owner_sizing_and_trials` (owner prefs account_size 50_000 reaches the backtest; trials count only owner's), `test_test_one_no_history_waits`, `test_weekly_run_retests_a_users_waiting_draft_with_owner_sizing`, `test_owner_without_prefs_uses_defaults`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `feat(builder): one-draft test mode sized by the draft's owner`.

### Task 3: API

**Files:**
- Modify: `backend/routers/settings.py`, `backend/ai/facts/user.py` (`built_strategies` fact scoped: global + the caller's own — make it `user=True`), `backend/chat/tools.py` if the tool needs the user id
- Test: `backend/tests/test_user_strategies_api.py`

**Interfaces:**
- Consumes: Tasks 1–2, `validate_spec`, `describe`, `slugify`, `draft._unique`, `rate_limit.allow`.
- Produces:
  - `GET /strategies/vocabulary` → `{"setups": {...}, "filters": {...}, "exits": {...}}` from `vocab` (tuples as JSON lists: numeric `{"min","max","step"}`, choice `{"choices": [...]}`, clock `{"time": [earliest, latest]}`, flag `{"flag": true}`).
  - `POST /strategies/describe` body `{"spec": {...}}` → `{"spec": clean, "description": str}` or 422 `{"detail": reason}`.
  - `POST /strategies/built` body `{"name": str (1–40), "thesis": str (≤ 200), "spec": {...}}` → validates against the user's own specs; enforces the three limits in Global Constraints (in order: active cap 409, one-testing 409, daily 429); inserts `{slug, spec, thesis, description, drafted_at, status: "testing", verdict: "", owner_id: user.id}`; `await draft.spawn_test(slug)` (a spawn exception is logged and the draft stays `testing`, retried by the weekly run); returns the stored doc (201).
  - `POST /strategies/built/{slug}/retire` and `/retest`: owner only (else 404 "No such strategy"); retire only from `active`, retest only from `rejected` (else 409); retest counts toward the daily limit and the one-testing rule, sets `testing`, spawns.
  - `GET /strategies/built` returns `store.visible(db, user.id)` grouped by status; each item adds `mine: bool`.

- [ ] **Step 1: Failing tests** for each endpoint's happy path and each limit, plus `test_other_users_strategy_is_invisible_and_untouchable`, `test_duplicate_of_own_refused_of_others_allowed`, `test_spawn_failure_leaves_draft_testing`, `test_vocabulary_matches_vocab_module`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `feat(strategies): compose, test, retire and re-test your own strategies over the API`.

### Task 4: Frontend and docs

**Files:**
- Create: `frontend/src/components/strategies/NewStrategySheet.jsx`, `frontend/src/components/strategies/MyStrategies.jsx`
- Modify: `frontend/src/pages/Strategies.jsx`, `frontend/src/utils/api.js`, `frontend/src/handbook/trading-and-money.md`, `PRODUCT.md`
- Test: `npm run build`; `npx vitest run`

**Interfaces:**
- Consumes: Task 3 endpoints.
- Produces UI (copy verbatim): button `New strategy`; sheet fields `Setup`, `Filters (up to 3)`, `Long` / `Short`, `Stop`, `Target`, `Name`, `Thesis`; preview line = `description` from `/strategies/describe` (debounced 400 ms; shows the 422 reason inline); submit `Test it`; section `Mine` with chips `Testing` / `Active` / `Rejected` / `Retired`, verdict, the existing `builtLine`; buttons `Retire`, `Re-test`; 409/429/422 details shown inline. While any of the user's strategies is `testing`, `MyStrategies` refetches `/strategies/built` every 10 s; it stops when none is. Active ones in the library show `Built · Yours`.
- Form builds the canonical spec `{"setup": {b: params}, "filters": {b: params}, "side", "stop", "target"}`; inputs come from `/strategies/vocabulary` (numeric → number input with min/max/step; choice → select; clock → time input; flag → checkbox).
- Docs: handbook "Your own strategies" subsection (scoping, limits, owner sizing, per-owner trial count); PRODUCT.md Practice → Strategies row.

- [ ] **Step 1:** Implement. **Step 2:** `npm run build` and `npx vitest run` pass. **Step 3: Commit** `feat(strategies): New strategy form and Mine section on Practice › Strategies [skip ci]`.

### Task 5: Deploy and smoke

- [ ] Full backend suite passes; push; in `/home/ubuntu/deploys/NeoTrade` pull, `GIT_SHA=$(git rev-parse HEAD) docker compose build backend ingest && docker compose up -d backend ingest`; `curl localhost:8000/health` → 200.
- [ ] Smoke as the admin user: `POST /strategies/built` with a simple ORB spec; within ~5 min `GET /strategies/built` shows it `active` or `rejected` with a verdict. Report it.
